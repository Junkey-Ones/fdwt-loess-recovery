"""从已验收的格点支撑记录生成掩膜和物候窗。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M3。
日志、路径和退出码由统一入口管理。
"""
from datetime import date, timedelta
from statistics import median_low


def prepare_support(records, grid, params, variant):
    """验证格点和面积，计算纳入条件、动态窗及中位回退。"""
    cfg, phenology = params["mask"], params["phenology"]
    support, masks, annual = {}, [], []
    by_grid = {row["grid_id"]: row for row in grid}
    for record in records:
        grid_id = record["grid_id"]
        if grid_id in support or grid_id not in by_grid:
            raise ValueError(f"空间支撑格点重复或未登记：{grid_id}")
        veg, excluded = record["vegetation_area_frac"], record["native_exclude_frac"]
        if not (0 <= veg <= 1 and 0 <= excluded <= 1):
            raise ValueError(f"格点面积比例无效：{grid_id}")
        include = (record["valid_landcover_years"] >= cfg["valid_years_min"]
                   and excluded < cfg["native_exclude_frac"] and veg >= cfg["veg_area_min"])
        land = record["baseline_land_cover"]
        mode = "fixed_season" if variant == "fixed_season" else "dynamic"
        common = dict(grid_version=by_grid[grid_id]["grid_version"], grid_id=grid_id)
        masks.append(dict(common, mask_version="main", valid_landcover_years=record["valid_landcover_years"],
                          native_exclude_frac=excluded, vegetation_area_frac=veg, mask_include=include,
                          baseline_land_cover=land, land_cover=land, exclusion_reason=None if include else "掩膜门槛"))
        valid = {}
        seen_years = set()
        for item in record["phenology"]:
            year = item["year"]
            if (year in seen_years or not 0 <= item["valid_pixel_area_frac"] <= 1
                    or item["valid_native_pixels"] < 0):
                raise ValueError(f"物候年份重复或像元覆盖无效：{grid_id} {year}")
            seen_years.add(year)
            if (item["valid_pixel_area_frac"] >= phenology["pixel_area_min"]
                    and item["valid_native_pixels"] >= phenology["native_pixels_min"]):
                segments = [(date.fromisoformat(a), date.fromisoformat(b)) for a, b in item["segments"]]
                if any(a > b for a, b in segments):
                    raise ValueError(f"物候窗起止倒置：{grid_id} {year}")
                if segments:
                    valid[year] = segments
        offsets = [( (min(a for a, _ in segments)-date(y, 1, 1)).days,
                     (max(b for _, b in segments)-date(y, 1, 1)).days)
                   for y, segments in valid.items()]
        windows = {}
        for year in range(params["time"]["year_start"], params["time"]["year_end"]+1):
            origin = date(year, 1, 1)
            fallback = False
            if mode == "fixed_season":
                first, last = phenology["fixed_months"]
                segments = [(date(year, first, 1), date(year, last+1, 1)-timedelta(days=1))]
            elif year in valid:
                segments = valid[year]
            elif len(valid) >= phenology["valid_years_min"]:
                segments = [(origin+timedelta(days=median_low(a for a, _ in offsets)),
                             origin+timedelta(days=median_low(b for _, b in offsets)))]
                fallback = True
            else:
                segments = []
            windows[year] = segments, fallback
            annual.append(dict(common, year=year, phenology_mode=mode, valid_phenology_years=len(valid),
                               phenology_fallback=fallback, num_cycles=len(segments),
                               active_window_start=min(a for a, _ in segments) if segments else None,
                               active_window_end=max(b for _, b in segments) if segments else None,
                               phenology_qc_status="passed" if segments else "insufficient"))
        support[grid_id] = dict(mask_include=include, windows=windows, land_cover=land, phenology_mode=mode)
    if set(support) != set(by_grid):
        raise ValueError("空间支撑缺少 M2 格点。")
    return support, masks, annual
