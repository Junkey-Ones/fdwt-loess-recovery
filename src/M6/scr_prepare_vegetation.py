"""原生 MODIS 四日 LAI 质控和逐格点逐年合成。"""
from collections import defaultdict
from datetime import date, timedelta
import re

import numpy as np


def lai_qc(raw, qc, extra, *, strict=False, allow_aerosol=False):
    """解码质量位；候选修订仅释放气溶胶位，原始填充值仍排除。"""
    # Extra_QC 第3位为气溶胶；116保留原124掩码中的其他质量限制。
    extra_mask = 116 if allow_aerosol else 124
    return ((raw <= 100) & (qc != 255) & ((qc & 29) == 0)
            & ((qc >> 5) <= (0 if strict else 1)) & (extra != 255)
            & ((extra & 3) <= 1) & ((extra & extra_mask) == 0))


def composite_weights(year, calendar):
    """按名义四日区间与候的交叠天数构造权重。"""
    start = date(year, 1, 1)
    stop = date(year + 1, 1, 1)
    result = []
    for row in calendar:
        left, right = row["start_date"], row["end_date"] + timedelta(days=1)
        weights = []
        first_slot = max(0, (left - start).days // 4)
        stop_slot = (min(right, stop) - start).days
        for offset in range(first_slot * 4, stop_slot, 4):
            a = start + timedelta(days=offset)
            days = (min(right, stop, a + timedelta(days=4)) - max(left, a)).days
            if days > 0:
                weights.append((offset // 4, days))
        result.append(weights)
    return result


def native_year(stack, weights, active):
    """原生像元先按日重叠合成候，再对有效活跃候等权平均。"""
    n = stack.shape[1]
    total, days = np.zeros(n), np.zeros(n)
    valid_count = np.zeros(n, dtype=np.int16)
    observed_pentads = []
    for pentad in active:
        # 四日 LAI 原始值最多 100，一候最长 6 天，整数累加后再转浮点求均值。
        numerator = np.zeros(n, dtype=np.uint16)
        denominator = np.zeros(n, dtype=np.uint8)
        for idx, count in weights[pentad]:
            values = stack[idx]
            valid = values <= 100
            numerator += np.where(valid, values, 0).astype(np.uint16) * count
            denominator += valid.astype(np.uint8) * count
        valid = denominator > 0
        if valid.any():
            observed_pentads.append(pentad)
        total += np.divide(numerator, denominator, out=np.zeros(n), where=valid)
        days += denominator
        valid_count += valid
    return total, days, valid_count, observed_pentads


def tile_geometry(ds):
    """核对 MODIS 原生正弦等积投影及瓦片范围。"""
    text = ds.attributes()["StructMetadata.0"]
    if ("Projection=GCTP_SNSOID" not in text or "PixelRegistration=HDFE_CENTER" not in text
            or ("GridOrigin=" in text and "GridOrigin=HDFE_GD_UL" not in text)):
        raise ValueError("MODIS 原生投影异常")
    def values(key):
        return tuple(float(x) for x in re.search(rf"{key}=\(([^)]+)\)", text)[1].split(","))
    left, top = values("UpperLeftPointMtrs")
    right, bottom = values("LowerRightMtrs")
    radius, *parameters = values("ProjParams")
    if radius != 6371007.181 or any(parameters):
        raise ValueError("MODIS 正弦投影参数异常")
    return left, top, right, bottom, radius


def tile_mapping(grid, bbox, resolution, geometry):
    """解析积分求裁边后的 ERA5-Land 格点与 MODIS 原生像元交叠。"""
    left, top, right, bottom, radius = geometry
    dx, dy = (right-left)/2400, (top-bottom)/2400
    west, south, east, north = bbox
    half = resolution / 2
    def positive(k, edge, low, high):
        end = np.clip(radius * np.arccos(np.clip(edge/k, -1, 1)), low, high)
        delta = end-low
        return 2*k*radius*np.cos((end+low)/(2*radius))*np.sin(delta/(2*radius))-edge*delta
    mapping = {}
    for cell, row in enumerate(grid):
        lo, hi = radius*np.deg2rad([max(south,row["lat"]-half),min(north,row["lat"]+half)])
        w, e = radius*np.deg2rad([max(west,row["lon"]-half),min(east,row["lon"]+half)])
        x0 = max(0,int(np.floor((w*np.cos(hi/radius)-left)/dx)))
        x1 = min(2400,int(np.ceil((e*np.cos(lo/radius)-left)/dx)))
        y0 = max(0,int(np.floor((top-hi)/dy)))
        y1 = min(2400,int(np.ceil((top-lo)/dy)))
        if x0 >= x1 or y0 >= y1:
            continue
        y,x = np.ogrid[y0:y1,x0:x1]
        a,b = left+x*dx,left+(x+1)*dx
        low,high = np.maximum(lo,top-(y+1)*dy),np.minimum(hi,top-y*dy)
        area = positive(e,a,low,high)-positive(e,b,low,high)-positive(w,a,low,high)+positive(w,b,low,high)
        good = (area > 0) & (a < e*np.cos(low/radius)) & (b > w*np.cos(high/radius))
        if good.any():
            mapping[cell] = ((y*2400+x)[good], area[good])
    return mapping


def vegetation_years(paths, grid, bbox, calendar, active, params, report):
    """逐瓦片逐年生成 LAI 年值，缺档按实际时间覆盖传播。"""
    from pyhdf.SD import SD, SDC

    settings = params["lai"]
    if settings["mask_version"] != "main" or settings["qc_version"] not in {"main","best_only","aerosol_allowed"}:
        raise ValueError("原生 LAI 前置仅支持主掩膜及 main／best_only／aerosol_allowed QA。")
    strict = settings["qc_version"] == "best_only"
    allow_aerosol = settings["qc_version"] == "aerosol_allowed"
    report("登记 LAI 文件", f"检查 {len(paths)} 个 HDF 的日期与瓦片编号")
    files = defaultdict(dict)
    tiles = set()
    for path in paths:
        match = re.fullmatch(r"MCD15A3H\.A(\d{4})(\d{3})\.(h\d{2}v\d{2})\.061\.\d+\.hdf",path.name)
        if not match:
            raise ValueError(f"LAI 文件名不符：{path.name}")
        year, day, tile = int(match[1]), int(match[2]), match[3]
        if not 1 <= day <= (date(year+1,1,1)-date(year,1,1)).days or (day-1)%4:
            raise ValueError(f"LAI 名义日期异常：{path.name}")
        slot = (day-1)//4
        if slot in files[year,tile]:
            raise ValueError(f"LAI 日期与瓦片重复：{path.name}")
        files[year,tile][slot] = path
        tiles.add(tile)
    first,last = settings["complete_years"]
    expected_tiles = {tile for _, tile in files}
    for year in range(first, last + 1):
        if {tile for y, tile in files if y == year} != expected_tiles:
            raise ValueError(f"LAI {year} 年缺少整块瓦片。")
    mode = next(iter(active))[2]
    mapping, geometries, tile_pixels = {}, {}, {}
    for done, tile in enumerate(sorted(tiles)):
        report("建立 LAI 格点映射", f"{tile} · 核对瓦片几何并计算交叠面积",
               done=done, total=len(tiles), unit="瓦片")
        sample = next(path for (_,t), slots in files.items() if t==tile for path in slots.values())
        ds = SD(str(sample),SDC.READ)
        try:
            geometries[tile] = tile_geometry(ds)
        finally:
            ds.end()
        cells = tile_mapping(grid, bbox, params["grid"]["resolution_deg"], geometries[tile])
        if cells:
            pixels = np.unique(np.concatenate([indices for indices, _ in cells.values()]))
            tile_pixels[tile] = pixels
            mapping[tile] = {cell: (np.searchsorted(pixels, indices), area)
                             for cell, (indices, area) in cells.items()}
    total_area = np.array([g["area_km2"] * 1e6
                           * (6371.007181 / params["native_era5land"]["earth_radius_km"])**2 for g in grid])
    result = []
    total = sum(len(slots) for (year, tile), slots in files.items()
                if first <= year <= last and tile in mapping)
    done = 0
    for year in range(first,last+1):
        year_calendar = calendar[year]
        weights = composite_weights(year,year_calendar)
        covered = np.zeros(len(grid))
        sums = np.zeros((len(grid),3))
        valid_pentads = np.zeros((len(grid),len(year_calendar)),dtype=bool)
        active_by_cell = [active.get((g["grid_id"],year,mode),[]) for g in grid]
        for tile in sorted(mapping):
            cells = mapping[tile]
            for cell, (_, area) in cells.items():
                covered[cell] += area.sum()
            pixels = tile_pixels[tile]
            slots = files.get((year,tile),{})
            if not slots:
                continue
            slots_in_year = ((date(year+1,1,1)-date(year,1,1)).days + 3)//4
            stack = np.full((slots_in_year,len(pixels)),255,dtype=np.uint8)
            for slot,path in sorted(slots.items()):
                report("合成 LAI 年值", f"{year} 年 {tile} · 读取与质控 {path.name}",
                       done=done, total=total, unit="HDF 文件")
                ds = SD(str(path),SDC.READ)
                try:
                    if tile_geometry(ds)!=geometries[tile]:
                        raise ValueError(f"LAI 瓦片几何变化：{path.name}")
                    layers = []
                    for name in ("Lai_500m","FparLai_QC","FparExtra_QC"):
                        field=ds.select(name)
                        try:
                            values=field[:]
                            if values.shape!=(2400,2400) or values.dtype!=np.uint8:
                                raise ValueError(f"LAI 字段维度或类型异常：{path.name} {name}")
                            if name=="Lai_500m":
                                attrs=field.attributes()
                                if not np.isclose(attrs["scale_factor"],settings["scale_factor"]) or attrs["add_offset"]!=0:
                                    raise ValueError(f"LAI 比例或偏移异常：{path.name}")
                            layers.append(values.ravel()[pixels])
                        finally:
                            field.endaccess()
                    raw,qc,extra=layers
                    stack[slot]=np.where(lai_qc(raw,qc,extra,strict=strict,allow_aerosol=allow_aerosol),raw,255)
                finally:
                    ds.end()
                done += 1
            for tile_done, (cell, (indices, area)) in enumerate(cells.items()):
                if tile_done % 8 == 0:
                    report("合成 LAI 年值", f"{year} 年 {tile} · 活跃候合成 {tile_done}/{len(cells)} 格点",
                           done=done, total=total, unit="HDF 文件")
                periods=active_by_cell[cell]
                if not periods:
                    continue
                pixel_stack = stack[:, indices]
                values, days, counts, observed = native_year(pixel_stack, weights, periods)
                valid=counts>0
                if valid.any():
                    sums[cell]+=(area[valid].sum(), np.dot(area[valid], values[valid]/counts[valid]), np.dot(area[valid],days[valid]))
                valid_pentads[cell, observed] = True
        report("合成 LAI 年值", f"{year} 年 · 核对覆盖并整理 {len(grid)} 个格点年值",
               done=done, total=total, unit="HDF 文件")
        if not np.allclose(covered,total_area,rtol=1e-6,atol=0):
            raise ValueError("LAI 原生瓦片覆盖与 M2 格点交叠面积不闭合。")
        for i,g in enumerate(grid):
            area,value,days=sums[i]
            periods=active_by_cell[i]
            space=min(1.,area/total_area[i])
            time=min(1.,days/(area*sum(year_calendar[p]["n_days"] for p in periods))) if area else 0.
            valid=space>=settings["annual_space_cover_min"] and time>=settings["annual_time_cover_min"]
            result.append(dict(grid_id=g["grid_id"],year=year,vegetation_product="mcd15a3h",phenology_mode=mode,
                               mask_version=settings["mask_version"],qc_version=settings["qc_version"],
                               vegetation_annual_mean=float(value/area*settings["scale_factor"]) if valid else None,
                               active_pentad_n=len(periods),valid_pentad_n=int(valid_pentads[i].sum()),
                               temporal_coverage=float(time),native_valid_area=float(area),
                               total_native_area=float(total_area[i]),spatial_coverage=float(space),
                               annual_valid=bool(valid),strict_qc_flag=strict,
                               exclusion_reason=None if valid else "活跃候缺失或覆盖不足"))
        report("合成 LAI 年值", f"{year} 年合成完成", done=done, total=total, unit="HDF 文件")
    return result
