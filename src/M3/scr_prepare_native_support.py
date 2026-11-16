"""scr_prepare_native_support.py：M3 原生地类和物候格点支撑。

作者：Codex；版本：2026-11-15。
读取：统一入口传入的M2格点、参数、边界及MCD12Q1/Q2.061文件。
生成：grid_support记录及QA/面积审计；由workflow原子发布到本次M3目录。
日志：report回调接入统一进度；本模块不自行登记或写入上游。
运行：python -m workflow.run_module M3；退出码由统一入口管理。
"""
from collections import Counter
from datetime import date, timedelta
import re

import numpy as np
from pyhdf.SD import SD, SDC
from src.M3.scr_prepare_support import prepare_support

EPOCH = date(1970, 1, 1)


def inventory(paths, product, years):
    """核验逐年瓦片键的唯一性和完整性。"""
    files = {}
    for path in sorted(paths):
        if not path.name.startswith(product + "."):
            continue
        match = re.fullmatch(rf"{product}\.A(\d{{4}})001\.(h\d{{2}}v\d{{2}})\.061\.\d+\.hdf", path.name)
        if match is None:
            raise ValueError(f"原生文件名不符：{path.name}")
        year, tile = int(match[1]), match[2]
        if year in years:
            key = year, tile
            if key in files:
                raise ValueError(f"重复瓦片：{key}")
            files[key] = path
    tiles = sorted({tile for _, tile in files})
    if not tiles or set(files) != {(year, tile) for year in years for tile in tiles}:
        raise ValueError(f"{product} 年度瓦片缺失")
    return files, tiles


def geometry(dataset):
    """解析原生正弦投影、球半径、瓦片边界和维度。"""
    text = dataset.attributes()["StructMetadata.0"]
    if "Projection=GCTP_SNSOID" not in text or "GridOrigin=HDFE_GD_UL" not in text:
        raise ValueError("原生瓦片投影或原点异常")
    def values(key):
        return tuple(float(x) for x in re.search(rf"{key}=\(([^)]+)\)", text)[1].split(","))
    width, height = (int(re.search(rf"{axis}Dim=(\d+)", text)[1]) for axis in "XY")
    left, top = values("UpperLeftPointMtrs")
    right, bottom = values("LowerRightMtrs")
    radius, *parameters = values("ProjParams")
    if (width, height) != (2400, 2400) or any(parameters) or radius != 6371007.181:
        raise ValueError("原生 MODIS 网格参数不符")
    return left, top, right, bottom, radius, width, height


def positive_integral(k, edge, low, high, radius):
    """对 max(k cos(y/R) - edge, 0) 在正纬度带解析积分。"""
    limit = radius * np.arccos(np.clip(edge / k, -1.0, 1.0))
    end = np.clip(limit, low, high)
    delta = end - low
    return 2 * k * radius * np.cos((end + low) / (2 * radius)) * np.sin(delta / (2 * radius)) - edge * delta


def overlap(grid, bbox, resolution, tile):
    """计算 MODIS 原生像元与裁切后的 ERA5-Land 格点的实际面积交叠。"""
    left, top, right, bottom, radius, width, height = tile
    dx, dy = (right - left) / width, (top - bottom) / height
    west, south, east, north = bbox
    half = resolution / 2
    result = []
    for index, row in enumerate(grid):
        lo, hi = radius * np.deg2rad([max(south, row["lat"] - half), min(north, row["lat"] + half)])
        w, e = radius * np.deg2rad([max(west, row["lon"] - half), min(east, row["lon"] + half)])
        x0 = max(0, int(np.floor((w * np.cos(hi / radius) - left) / dx)))
        x1 = min(width, int(np.ceil((e * np.cos(lo / radius) - left) / dx)))
        y0 = max(0, int(np.floor((top - hi) / dy)))
        y1 = min(height, int(np.ceil((top - lo) / dy)))
        if x0 >= x1 or y0 >= y1:
            continue
        iy, ix = np.ogrid[y0:y1, x0:x1]
        a = left + ix * dx
        b = a + dx
        lower = np.maximum(lo, top - (iy + 1) * dy)
        upper = np.minimum(hi, top - iy * dy)
        area = (positive_integral(e, a, lower, upper, radius)
                - positive_integral(e, b, lower, upper, radius)
                - positive_integral(w, a, lower, upper, radius)
                + positive_integral(w, b, lower, upper, radius))
        # 仅保留几何上相交的像元，避免积分差的浮点误差计入像元数。
        intersects = (a < e * np.cos(lower / radius)) & (b > w * np.cos(upper / radius))
        if np.any(area[intersects] < -0.001):
            raise ValueError("交叠面积积分产生负值")
        y, x = np.where(intersects & (area > 0))
        result.append((np.full(x.size, index, dtype=np.int32), ((y + y0) * width + x + x0).astype(np.int32), area[y, x]))
    if not result:
        return np.empty(0, dtype=np.int32), np.empty(0, dtype=np.int32), np.empty(0)
    return tuple(np.concatenate(column) for column in zip(*result))


def field(dataset, name, shape, valid_range, fill):
    """读取原生 SDS 并核验维度、填充值和有效范围。"""
    source = dataset.select(name)
    try:
        data = source[:]
        attrs = source.attributes()
        if data.shape != shape or attrs.get("_FillValue", fill) != fill or data.dtype.kind not in "iu":
            raise ValueError(f"{name} 的维度、类型或填充值异常")
        low, high = valid_range
        if np.any(((data < low) | (data > high)) & (data != fill)):
            raise ValueError(f"{name} 存在未声明的越界值")
        return data.reshape((-1,) + shape[2:])
    finally:
        source.endaccess()


def dominant(areas):
    """面积并列时取较小的 IGBP 编码，保留并列标记。"""
    peak = areas.max(axis=1)
    tied = np.isclose(areas, peak[:, None], rtol=1e-10, atol=1e-6)
    return np.where(peak > 0, tied.argmax(axis=1) + 1, 0), (peak > 0) & (tied.sum(axis=1) > 1)


def weighted_dates(grid_id, values, area, n_grid):
    """逐格点取累计面积首次达到一半的绝对日期。"""
    if not len(grid_id):
        return np.full(n_grid, -1, dtype=np.int32)
    order = np.lexsort((values, grid_id))
    keys, values, area = grid_id[order], values[order], area[order]
    unique, first = np.unique(keys, return_index=True)
    result = np.full(n_grid, -1, dtype=np.int32)
    for cell, a, b in zip(unique, first, [*first[1:], len(keys)]):
        cumulative = np.cumsum(area[a:b], dtype=np.float64)
        result[cell] = values[a + np.searchsorted(cumulative, cumulative[-1] / 2)]
    return result


def merge_segments(segments):
    """合并重叠或紧邻的闭区间，保留周期之间的空档。"""
    merged = []
    for first, last in sorted(segments):
        if merged and first <= merged[-1][1] + 1:
            merged[-1][1] = max(last, merged[-1][1])
        else:
            merged.append([first, last])
    return [[(EPOCH + timedelta(days=int(day))).isoformat() for day in span] for span in merged]


def sop_examples():
    """核对 QA 位向量、跨年、多周期和地类面积示例。"""
    expected = [[0]*7, [1]*7, [3,2,1,1,2,3,3], [1,2,0,1,0,2,3], [3]*7]
    assert [[(q >> (2*i)) & 3 for i in range(7)] for q in (0,5461,15963,14409,16383)] == expected
    def epoch(text):
        return (date.fromisoformat(text) - EPOCH).days
    segments = [["2020-12-20","2021-04-10"], ["2021-07-01","2021-09-30"]]
    assert merge_segments([[epoch(a), epoch(b)] for a,b in segments]) == segments
    assert weighted_dates(np.array([0,0,1]), np.array([15,25,10]), np.array([1.,3.,1.]), 3).tolist() == [25,10,-1]
    area = np.zeros((1,17))
    area[0,[0,9]] = .5
    code, tie = dominant(area)
    assert code.tolist() == [1] and tie.tolist() == [True]


def landcover(files, tiles, mapping, geoms, cfg, area, year_range, audit, report):
    """按原生像元的多年记录判定永久排除，按交叠面积汇总地类。"""
    n = len(area)
    vegetated = np.zeros(n)
    excluded = np.zeros(n)
    annual = np.zeros((len(year_range), n, 17))
    baseline = np.zeros((n, 17))
    keep = cfg["igbp_keep"]
    for tile in tiles:
        cells, pixels, weights = mapping[tile]
        unique, inverse = np.unique(pixels, return_inverse=True)
        if not len(unique):
            continue
        valid_years = np.zeros(len(unique), dtype=np.uint8)
        exclude_years = np.zeros_like(valid_years)
        baseline_areas = np.zeros((len(unique), 17), dtype=np.uint8)
        for i, year in enumerate(year_range):
            path = files[year, tile]
            ds = SD(str(path), SDC.READ)
            try:
                if geometry(ds) != geoms[tile]:
                    raise ValueError(f"瓦片网格变化：{path.name}")
                code = field(ds, "LC_Type1", (2400,2400), (1,17), 255)[unique]
                qc = field(ds, "QC", (2400,2400), (0,10), 255)[unique]
                lw = field(ds, "LW", (2400,2400), (1,2), 255)[unique]
            finally:
                ds.end()
            valid = (code != 255) & ~np.isin(qc, (1,3,10,255)) & ((lw == 2) | ((lw == 1) & (code == 17)))
            land = valid & (lw == 2)
            valid_years += valid
            exclude_years += valid & ~np.isin(code, keep)
            good = land[inverse]
            bins = cells[good] * 17 + code[inverse[good]].astype(np.int32) - 1
            annual[i] += np.bincount(bins, weights=weights[good], minlength=n*17).reshape(n,17)
            if cfg["baseline_years"][0] <= year <= cfg["baseline_years"][1]:
                native = np.flatnonzero(land)
                baseline_areas[native, code[native] - 1] += 1
            audit["land_qc8"] += int((land & (qc == 8)).sum())
            audit["land_qc9"] += int((land & (qc == 9)).sum())
            audit["land_water_17"] += int((valid & (lw == 1)).sum())
        eligible = valid_years >= cfg["valid_years_min"]
        permanent = eligible & (exclude_years >= cfg["native_exclude_frac"] * valid_years)
        # 对未永久排除的像元按有效年份中保留类的比例折算植被面积。
        retained = np.divide(valid_years - exclude_years, valid_years,
                             out=np.zeros(len(unique)), where=eligible & ~permanent)
        for mask, result in ((permanent, excluded), (retained, vegetated)):
            result += np.bincount(cells, weights=weights * mask[inverse], minlength=n)
        base_code, _ = dominant(baseline_areas)
        good = base_code[inverse] > 0
        bins = cells[good] * 17 + base_code[inverse[good]].astype(np.int32) - 1
        baseline += np.bincount(bins, weights=weights[good], minlength=n*17).reshape(n,17)
        report("聚合原生地类", f"地类瓦片 {tile} 完成")
    annual_code, annual_ties = dominant(annual.reshape(-1,17))
    audit["land_annual_ties"] = int(annual_ties.sum())
    base_code, base_ties = dominant(baseline)
    audit["land_baseline_ties"] = int(base_ties.sum())
    valid_count = (annual_code.reshape(len(year_range), n) > 0).sum(axis=0)
    classes = [None, *["forest"]*5, *["grassland"]*5, "other", "cropland", "other", "cropland", *["other"]*3]
    return np.clip(vegetated/area, 0, 1), np.clip(excluded/area, 0, 1), valid_count, [classes[code] for code in base_code]


def phenology(files, tiles, mapping, geoms, area, years, audit, report):
    """在每个有效周期内按实际交叠面积汇总起止日期。"""
    n = len(area)
    result = [[] for _ in area]
    for year in years:
        coverage = np.zeros(n)
        count = np.zeros(n, dtype=np.int32)
        pieces = [[], []]
        for tile in tiles:
            path = files[year, tile]
            cells, pixels, weights = mapping[tile]
            unique, inverse = np.unique(pixels, return_inverse=True)
            if not len(unique):
                continue
            ds = SD(str(path), SDC.READ)
            try:
                if geometry(ds) != geoms[tile]:
                    raise ValueError(f"瓦片网格变化：{path.name}")
                cycles = field(ds, "NumCycles", (2400,2400), (1,7), 32767)[unique]
                shape = (2400,2400,2)
                start = field(ds,"Greenup",shape,(11138,32766),32767)[unique]
                end = field(ds,"Dormancy",shape,(11138,32766),32767)[unique]
                overall = field(ds,"QA_Overall",shape,(0,3),32767)[unique]
                detailed = field(ds,"QA_Detailed",shape,(0,16383),32767)[unique]
                field(ds,"EVI_Amplitude",shape,(0,10000),32767)
            finally:
                ds.end()
            valid = ((cycles[:,None] >= np.array([1,2])) & (cycles[:,None] <= 7)
                     & (overall <= 1) & (start != 32767) & (end != 32767))
            audit["phen_reversed_pixels"] += int((valid & (end < start)).sum())
            valid &= end >= start
            for bit in range(7):
                values = ((detailed >> (2*bit)) & 3)[valid & (detailed != 32767)]
                for level, total in enumerate(np.bincount(values, minlength=4)):
                    audit[f"phen_detail_{bit}_{level}"] += int(total)
            audit["phen_detail_missing"] += int((valid & (detailed == 32767)).sum())
            good = valid.any(axis=1)[inverse]
            coverage += np.bincount(cells[good], weights=weights[good], minlength=n)
            count += np.bincount(cells[good], minlength=n).astype(np.int32)
            for cycle in range(2):
                good = valid[:,cycle][inverse]
                pix = inverse[good]
                pieces[cycle].append((cells[good], weights[good], start[pix,cycle], end[pix,cycle]))
        windows = [[] for _ in area]
        for cycle in pieces:
            keys, weight, start, end = (np.concatenate(col) for col in zip(*cycle))
            first = weighted_dates(keys, start, weight, n)
            last = weighted_dates(keys, end, weight, n)
            audit["phen_reversed_grid_cycles"] += int(((first >= 0) & (last < first)).sum())
            for i in np.flatnonzero((first >= 0) & (last >= first)):
                windows[i].append((first[i], last[i]))
        for i in range(n):
            result[i].append(dict(year=year, valid_pixel_area_frac=float(np.clip(coverage[i]/area[i],0,1)),
                                  valid_native_pixels=int(count[i]), segments=merge_segments(windows[i])))
        report("聚合原生物候", f"物候年度 {year} 完成")
    return result



def native_support_sources(root, params):
    """发现原始年度瓦片并在计算前拒绝部分缺档或重复键。"""
    paths = sorted(path for product in ("MCD12Q1", "MCD12Q2")
                   for path in (root / "data/raw/modis" / product / "V061").rglob("*.hdf"))
    if not paths:
        return []
    cfg = params["mask"]
    q1, tiles = inventory(paths, "MCD12Q1", range(cfg["valid_year_start"], cfg["valid_year_end"] + 1))
    q2, other = inventory(paths, "MCD12Q2", range(params["time"]["year_start"], params["time"]["year_end"] + 1))
    if tiles != other:
        raise ValueError("两产品瓦片集合不同")
    return sorted([*q1.values(), *q2.values()])


def prepare_native_support(paths, grid, params, bbox, report):
    """沿用已验收本地构建公式，返回格点支撑和审计，不写共享登记。"""
    if not grid:
        raise ValueError("M2格点清单为空")
    cfg = params["mask"]
    q1_years = range(cfg["valid_year_start"], cfg["valid_year_end"]+1)
    q2_years = range(params["time"]["year_start"], params["time"]["year_end"]+1)
    q1, tiles = inventory(paths, "MCD12Q1", q1_years)
    q2, other_tiles = inventory(paths, "MCD12Q2", q2_years)
    if tiles != other_tiles:
        raise ValueError("两产品瓦片集合不同")
    mapping, geoms = {}, {}
    area = np.zeros(len(grid))
    for tile in tiles:
        ds = SD(str(q1[q1_years.start,tile]), SDC.READ)
        try:
            geoms[tile] = geometry(ds)
        finally:
            ds.end()
        mapping[tile] = overlap(grid,bbox,params["grid"]["resolution_deg"],geoms[tile])
        ids, _, weights = mapping[tile]
        area += np.bincount(ids, weights=weights, minlength=len(grid))
    expected = np.array([row["area_km2"] for row in grid]) * (next(iter(geoms.values()))[4]/params["native_era5land"]["earth_radius_km"])**2
    error = np.abs(area/expected - 1)
    if error.max() > 1e-6:
        worst = sorted(range(len(grid)),key=lambda i:error[i],reverse=True)[:5]
        raise ValueError(f"原生瓦片无法覆盖所有 M2 格点：{[(grid[i]['grid_id'],grid[i]['lon'],grid[i]['lat'],round(float(area[i]/expected[i]),6)) for i in worst]}")
    report("核验原生面积", f"面积闭合验证通过，最大相对误差 {error.max():.2g}")
    audit = Counter()
    vegetation, excluded, years, classes = landcover(q1,tiles,mapping,geoms,cfg,expected,q1_years,audit,report)
    seasons = phenology(q2,tiles,mapping,geoms,expected,q2_years,audit,report)
    rows = [dict(grid_id=g["grid_id"],vegetation_area_frac=float(vegetation[i]),
                 native_exclude_frac=float(excluded[i]),valid_landcover_years=int(years[i]),
                 baseline_land_cover=classes[i],phenology=seasons[i]) for i,g in enumerate(grid)]
    _, masks, annual = prepare_support(rows,grid,params,"main")
    audit.update(dict(grid_cells=len(grid), landcover_files=len(q1), phenology_files=len(q2),
                      mask_included=sum(x["mask_include"] for x in masks),
                      phenology_dynamic=sum(x["phenology_qc_status"]=="passed" and not x["phenology_fallback"] for x in annual),
                      phenology_fallback=sum(x["phenology_fallback"] for x in annual),
                      phenology_insufficient=sum(x["phenology_qc_status"]!="passed" for x in annual)))
    audit["max_relative_area_error"] = float(error.max())
    return rows, dict(audit)
