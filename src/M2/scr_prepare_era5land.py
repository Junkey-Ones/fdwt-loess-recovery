"""脚本名：scr_prepare_era5land.py（M2 · ERA5-Land 日和候预处理）
功能简介：将 M1 放行的小时场转换为原生网格水量、温度和 73 候序列。
作者：Codex
版本：v0.1.0
读取数据：M1 通过的 NetCDF 与冻结运行配置。
生成数据：grid_day_era5land、grid_pentad_base_era5land、日历及网格清单。
其他文件：运行身份和审计回执由编排层写入。
运行示例：python -m workflow.run_module M2 --run-alias 2026-11-10_主分析
退出码：由统一入口定义。
"""
from datetime import date, timedelta

from src.M1.scr_audit_era5land import FIELDS, PRODUCT, era5land_years, expected_files, native_axes, read_field

STATE = ("sm_0_100_mm", "sm_deep_mm", "t2m_c")
FLUX_NAMES = {"tp": "p_mm", "e": "et_loss_mm", "pev": "pet_loss_mm",
              "sro": "runoff_surface_mm", "ssro": "runoff_subsurface_mm"}
FLUX = (*FLUX_NAMES.values(), "runoff_mm", "balance_mm")


def pentad_calendar(first, last, count, base_year):
    """生成连续候键，年末候吸收平闰年余日。"""
    rows = []
    for year in range(first, last + 1):
        origin = date(year, 1, 1)
        for pentad in range(1, count + 1):
            start = origin + timedelta(days=5 * (pentad - 1))
            end = date(year, 12, 31) if pentad == count else start + timedelta(days=4)
            t_abs = (year - base_year) * count + pentad
            rows.append({"t_abs": t_abs, "year": year, "pentad": pentad, "start_date": start,
                         "end_date": end, "n_days": (end - start).days + 1,
                         "is_leap_year": (date(year + 1, 1, 1) - origin).days == 366,
                         "is_pentad73": pentad == count, "previous_t_abs": t_abs - 1 if rows else None,
                         "next_t_abs": t_abs + 1})
    rows[-1]["next_t_abs"] = None
    return rows


def daily_flux(name, current, next_midnight, settings):
    """使用 D+1 00 UTC 的终值；当前日 00 UTC 属于前一天。"""
    import numpy as np

    end = np.concatenate((current[24::24], next_midnight[None]), axis=0)
    steps = current.reshape(-1, 24, *current.shape[1:])[:, 1:]
    complete = np.isfinite(steps).all(axis=1) & np.isfinite(end)
    tolerance = settings["water_roundoff_m"]
    if name not in {"e", "pev"}:
        if np.any(end - steps[:, -1] < -tolerance):
            raise ValueError(f"{name} 的第 24 步累计回落。")
        end = np.maximum(end, 0)
    sign = -1 if name in {"e", "pev"} else 1
    return np.where(complete, sign * settings["mm_per_m"] * end, np.nan)


def aggregate_pentad(days, config):
    """按状态有效日和通量完整性规则形成候值。"""
    import numpy as np

    result = {}
    counts, gaps = [], []
    for name in STATE:
        values = days[name]
        valid = np.isfinite(values)
        count = valid.sum(axis=0)
        run = np.zeros_like(count)
        longest = run.copy()
        for day in valid:
            run = np.where(day, 0, run + 1)
            longest = np.maximum(longest, run)
        ok = ((count >= config["state_min_valid_days"])
              & (longest <= config["state_max_consecutive_missing_days"]))
        result[name] = np.where(ok, np.nansum(values, axis=0) / np.maximum(count, 1), np.nan)
        counts.append(count)
        gaps.append(longest)
    if not config["flux_requires_complete_days"]:
        raise ValueError("当前 M2 仅支持完整日通量。")
    for name in FLUX:
        result[name] = np.sum(days[name], axis=0)
    result["p_mm_per_day"] = result["p_mm"] / len(days["p_mm"])
    result["p_5day_equivalent_mm"] = 5 * result["p_mm_per_day"]
    result["state_valid_days"] = np.minimum.reduce(counts)
    result["state_max_consecutive_missing_days"] = np.maximum.reduce(gaps)
    result["flux_complete_flag"] = np.logical_and.reduce([np.isfinite(result[name]) for name in FLUX])
    return result


def spatial_indices(lat, lon, bbox, resolution):
    """返回研究区内按纬度降序和经度升序排列的轴索引。"""
    import numpy as np

    west, south, east, north = bbox
    half = resolution / 2
    iy = np.argsort(lat)[::-1]
    ix = np.argsort(lon)
    iy = iy[(lat[iy] + half > south) & (lat[iy] - half < north)]
    ix = ix[(lon[ix] + half > west) & (lon[ix] - half < east)]
    return iy, ix


def spatial_grid(lat, lon, bbox, resolution, radius_km, version):
    """按排序后的轴生成格点键并计算实际矩形交叠面积。"""
    import numpy as np

    west, south, east, north = bbox
    half = resolution / 2
    iy, ix = spatial_indices(lat, lon, bbox, resolution)
    rows = []
    for y in lat[iy]:
        for x in lon[ix]:
            dlon = min(east, x + half) - max(west, x - half)
            sin_span = np.sin(np.deg2rad(min(north, y + half))) - np.sin(np.deg2rad(max(south, y - half)))
            rows.append({"grid_version": version, "grid_id": f"g{len(rows) + 1:06d}",
                         "lon": round(float(x), 8), "lat": round(float(y), 8),
                         "area_km2": float(radius_km ** 2 * np.deg2rad(dlon) * sin_span),
                         "boundary_include": True, "grid_geometry_id": version,
                         "valid_area_fraction": 1.0, "grid_qc_status": "passed"})
    return iy, ix, rows


def monthly_values(task):
    """读取一个月的原生场，按切片字节预算归约为日尺度数组。"""
    from netCDF4 import Dataset
    import numpy as np

    year, month, paths, following, bbox, resolution, settings = task
    next_start = date(year + (month == 12), month % 12 + 1, 1)
    n_days = (next_start - date(year, month, 1)).days
    scale = settings["mm_per_m"]

    def axes(source):
        time_name = "valid_time" if "valid_time" in source.variables else "time"
        lat, lon = (np.asarray(source[name][:]) for name in ("latitude", "longitude"))
        iy, ix = spatial_indices(lat, lon, bbox, resolution)
        return time_name, iy, ix

    def read(source, coords, name, start, stop):
        time_name, iy, ix = coords
        field = read_field(source, name, time_name, slice(start, stop),
                           slice(iy.min(), iy.max() + 1), slice(ix.min(), ix.max() + 1))
        return field[:, ::-1 if iy[0] > iy[-1] else 1, ::-1 if ix[0] > ix[-1] else 1]

    def daily_mean(array):
        # 保留原空间索引生成的时间连续布局，避免改变小时求和次序。
        array = np.asfortranarray(array)
        return array.reshape(-1, 24, *array.shape[1:]).mean(axis=1)

    values = {}
    with Dataset(paths["instant"]) as source:
        coords = axes(source)
        _, iy, ix = coords
        bytes_per_day = 24 * len(iy) * len(ix) * np.dtype(np.float64).itemsize
        days_per_batch = max(1, (64 * 2**20) // bytes_per_day)
        chunks = range(0, n_days, days_per_batch)
        for start in chunks:
            stop = min(n_days, start + days_per_batch)
            a, b = start * 24, stop * 24
            root_soil = sum(read(source, coords, f"swvl{i}", a, b) * thickness
                            for i, thickness in enumerate(settings["root_layer_thickness_m"], 1))
            part = {
                "sm_0_100_mm": daily_mean(root_soil) * scale,
                "sm_deep_mm": daily_mean(read(source, coords, "swvl4", a, b))
                * settings["deep_layer_thickness_m"] * scale,
                "t2m_c": daily_mean(read(source, coords, "t2m", a, b)) - settings["kelvin_offset"],
            }
            for field, array in part.items():
                if field not in values:
                    values[field] = np.empty((n_days, *array.shape[1:]), dtype=float)
                values[field][start:stop] = array
    for group in ("accumulated", "runoff_components"):
        with Dataset(paths[group]) as source, Dataset(following[group]) as next_source:
            coords, next_coords = axes(source), axes(next_source)
            for field in FIELDS[group]:
                output = np.empty_like(values["t2m_c"])
                for start in chunks:
                    stop = min(n_days, start + days_per_batch)
                    a, b = start * 24, stop * 24
                    if stop == n_days:
                        current = read(source, coords, field, a, b)
                        midnight = read(next_source, next_coords, field, 0, 1)[0]
                    else:
                        data = read(source, coords, field, a, b + 1)
                        current, midnight = data[:-1], data[-1]
                    output[start:stop] = daily_flux(field, current, midnight, settings)
                values[FLUX_NAMES[field]] = output
    values["runoff_mm"] = values["runoff_surface_mm"] + values["runoff_subsurface_mm"]
    values["balance_mm"] = values["p_mm"] - values["et_loss_mm"] - values["runoff_mm"]
    return values


def prepare_era5land(root, destination, params, bbox, tables, progress, runtime=None):
    """按年流式写日表和候表。调用方须先校验 M1 哈希回执。"""
    from contextlib import ExitStack, closing
    from netCDF4 import Dataset
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq
    from workflow.runtime import ordered_tasks, resolve_runtime

    settings = params["native_era5land"]
    first, last = era5land_years(params)
    calendar = pentad_calendar(first, last, params["time"]["pentads_per_year"], params["time"]["index_base_year"])
    entries = list(expected_files(settings, first, last))
    monthly = {(start.year, start.month, group): root / path
               for path, group, _, start, _ in entries}
    terminal = root / entries[-1][0]
    version = params["grid"]["main_version"]

    def save_rows(name, rows):
        columns = {key: [row.get(key) for row in rows] for key in tables[name]["columns"]}
        for key, values in columns.items():
            if all(value is None for value in values):
                columns[key] = pa.array(values, type=pa.string())
        pq.write_table(pa.table(columns), destination / f"{name}.parquet")

    with Dataset(monthly[first, 1, "instant"]) as source:
        _, _, lat, lon = native_axes(source)
    _, _, grid = spatial_grid(lat, lon, bbox, params["grid"]["resolution_deg"],
                              settings["earth_radius_km"], version)
    if not grid:
        raise ValueError("冻结边界与原生网格没有交叠。")
    save_rows("time_pentad_calendar", calendar)
    west, south, east, north = bbox
    lat0 = np.deg2rad((south+north)/2)
    lon0 = (west+east)/2
    radius = settings["earth_radius_km"]
    size = params["block"]["km"]
    for cell in grid:
        lat = np.deg2rad(cell["lat"])
        dlon = np.deg2rad(cell["lon"]-lon0)
        factor = np.sqrt(2/(1 + np.sin(lat0)*np.sin(lat) + np.cos(lat0)*np.cos(lat)*np.cos(dlon)))
        x = radius*factor*np.cos(lat)*np.sin(dlon)
        y = radius*factor*(np.cos(lat0)*np.sin(lat)-np.sin(lat0)*np.cos(lat)*np.cos(dlon))
        cell["block_id"] = f"{int(np.floor(x/size))}:{int(np.floor(y/size))}"
    save_rows("grid_manifest", grid)
    grid_ids = pa.array([row["grid_id"] for row in grid])

    def batch(name, values, time_columns):
        width = len(grid_ids)
        valid = np.logical_and.reduce([np.isfinite(values[field]) for field in (*STATE, *FLUX)]).ravel()
        n = len(valid)
        columns = {"product_code": pa.repeat(PRODUCT, n), "grid_version": pa.repeat(version, n),
                   "grid_id": pa.concat_arrays([grid_ids] * (n // width)),
                   "support_id": pa.repeat("own_full", n),
                   "valid_native_area_frac": valid.astype(float),
                   "qc_status": np.where(valid, "passed", "missing"),
                   "missing_reason": np.where(valid, "", "原生时段缺测")}
        columns.update({key: pa.concat_arrays([pa.repeat(value, width) for value in times])
                        for key, times in time_columns.items()})
        columns.update({key: pa.array(value.ravel(), from_pandas=True) for key, value in values.items()})
        return pa.table({key: columns[key] for key in tables[name]["columns"]})

    resources = runtime or resolve_runtime({"profile": "low"})

    def month_tasks():
        for year in range(first, last + 1):
            for month in range(1, 13):
                next_year, next_month = year + (month == 12), month % 12 + 1
                paths = {group: monthly[year, month, group] for group in FIELDS}
                following = {group: monthly.get((next_year, next_month, group), terminal)
                             for group in ("accumulated", "runoff_components")}
                yield year, month, paths, following, bbox, params["grid"]["resolution_deg"], settings

    with ExitStack() as stack:
        results = stack.enter_context(closing(ordered_tasks(
            monthly_values, month_tasks(), resources, task_gib=0.75, reads_disk=True)))
        writers = {}

        def write(name, table):
            if name not in writers:
                writers[name] = stack.enter_context(
                    pq.ParquetWriter(destination / f"{name}_{PRODUCT}.parquet", table.schema))
            writers[name].write_table(table)

        for year in range(first, last + 1):
            day_offset = 0
            year_days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
            daily = {}
            for month in range(1, 13):
                values = next(results)
                progress("M2 日和候预处理", f"{year}-{month:02d}",
                         ((year - first) * 12 + month) / ((last - first + 1) * 12))
                n_days = len(values["p_mm"])
                for field, array in values.items():
                    if field not in daily:
                        daily[field] = np.empty((year_days, *array.shape[1:]), dtype=float)
                    daily[field][day_offset:day_offset + n_days] = array
                for offset in range(0, n_days, 4):
                    stop = min(n_days, offset + 4)
                    write("grid_day", batch("grid_day", {key: value[offset:stop] for key, value in values.items()},
                                            {"date": [date(year, month, index + 1) for index in range(offset, stop)]}))
                day_offset += n_days
            for row in calendar[(year - first) * params["time"]["pentads_per_year"]:
                                (year - first + 1) * params["time"]["pentads_per_year"]]:
                start = (row["start_date"] - date(year, 1, 1)).days
                values = aggregate_pentad({name: array[start:start + row["n_days"]]
                                          for name, array in daily.items()}, params["time"])
                keys = ("t_abs", "year", "pentad", "start_date", "end_date", "n_days")
                write("grid_pentad_base", batch("grid_pentad_base", values, {key: [row[key]] for key in keys}))
