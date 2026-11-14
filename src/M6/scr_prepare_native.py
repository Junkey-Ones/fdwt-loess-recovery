"""使用冻结活跃候和格点清单生成 M6 的两张原生输入表。"""
from collections import defaultdict


def native_sources(root, params, missing):
    """列出本次前置需要读取的原始文件。"""
    raw = root / "data/raw"
    first,last = params["lai"]["complete_years"]
    modis = raw / "modis/MCD15A3H/V061"
    soil = raw / "soilgrids/v2.0"
    terrain = raw / "nasadem/HGT.001"
    sources = {}
    if "vegetation_grid_year" in missing:
        files = sorted(path for year in range(first, last + 1)
                       for path in modis.rglob(f"MCD15A3H.A{year}*.hdf"))
        if files:
            sources["vegetation_grid_year"] = files
    if "grid_static_covariates" in missing:
        layers = [soil/f"{variable}_{depth}cm_mean.tif" for variable in ("sand","clay")
                  for depth in ("0-5","5-15","15-30")]
        tiles = sorted(terrain.glob("NASADEM_HGT_*.zip"))
        if all(path.is_file() for path in layers) and tiles:
            sources["grid_static_covariates"] = layers + tiles
    return sources


def prepare_native_inputs(sources, tables, params, bbox, report, *, workers=1):
    """按 M3 冻结的活跃候和空间支撑生成待发布记录。"""
    import pyarrow.parquet as pq
    from src.M6.scr_prepare_static import static_covariates
    from src.M6.scr_prepare_vegetation import vegetation_years

    report("读取冻结格点", tables["grid_manifest"].name)
    grid = pq.read_table(tables["grid_manifest"]).to_pylist()
    result = {}
    if "grid_static_covariates" in sources:
        files = sources["grid_static_covariates"]
        result["grid_static_covariates"] = static_covariates(
            files[:6], files[6:], grid, bbox, params, report, workers=workers)
    if "vegetation_grid_year" in sources:
        report("读取 LAI 活跃候", "读取冻结候历")
        calendar = defaultdict(list)
        for row in pq.read_table(tables["time_pentad_calendar"]).to_pylist():
            calendar[row["year"]].append(row)
        for rows in calendar.values():
            rows.sort(key=lambda row:row["pentad"])
        active = defaultdict(list)
        columns = ["grid_id","year","pentad","phenology_mode"]
        report("读取 LAI 活跃候", "从冻结表筛选有效活跃候")
        active_table = pq.read_table(tables["grid_active_pentad"], columns=columns,
                                     filters=[("active_flag", "=", True)])
        total = active_table.num_rows
        done = 0
        for batch in active_table.to_batches(max_chunksize=8192):
            for row in batch.to_pylist():
                active[row["grid_id"],row["year"],row["phenology_mode"]].append(row["pentad"]-1)
            done += batch.num_rows
            report("读取 LAI 活跃候", "按格点、年份和物候方案整理", done=done, total=total, unit="记录")
        del active_table
        if len({key[2] for key in active})!=1:
            raise ValueError("M6 原生 LAI 需要 M3 提供唯一物候方案的有效活跃候。")
        included = {key[0] for key in active}
        result["vegetation_grid_year"] = vegetation_years(sources["vegetation_grid_year"],
            [row for row in grid if row["grid_id"] in included],bbox,calendar,active,params,report)
    return result
