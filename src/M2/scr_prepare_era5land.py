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


def spatial_grid(lat, lon, bbox, resolution, radius_km, version):
    """按纬度降序和经度升序生成格点键并计算实际矩形交叠面积。"""
    import numpy as np

    west, south, east, north = bbox
    half = resolution / 2
    iy = np.argsort(lat)[::-1]
    ix = np.argsort(lon)
    iy = iy[(lat[iy] + half > south) & (lat[iy] - half < north)]
    ix = ix[(lon[ix] + half > west) & (lon[ix] - half < east)]
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


def prepare_era5land(root, destination, params, bbox, tables, progress):
    """按年流式写日表和候表。调用方须先校验 M1 哈希回执。"""
    from contextlib import ExitStack
    from netCDF4 import Dataset
    import numpy as np
    import pyarrow as pa
    import pyarrow.parquet as pq

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
    grid_ids = [row["grid_id"] for row in grid]

    def load(path, fields, selection):
        with Dataset(path) as source:
            time_name, _, lat, lon = native_axes(source)
            iy, ix, _ = spatial_grid(lat, lon, bbox, params["grid"]["resolution_deg"],
                                      settings["earth_radius_km"], version)
            return {name: read_field(source, name, time_name, selection)[:, iy][:, :, ix]
                    for name in fields}

    def batch(name, values, time_columns):
        n = len(grid_ids)
        valid = np.logical_and.reduce([np.isfinite(values[field]) for field in (*STATE, *FLUX)]).ravel()
        columns = {"product_code": [PRODUCT] * n, "grid_version": [version] * n,
                   "grid_id": grid_ids, "support_id": ["own_full"] * n,
                   "valid_native_area_frac": valid.astype(float),
                   "qc_status": np.where(valid, "passed", "missing"),
                   "missing_reason": np.where(valid, "", "原生时段缺测")}
        columns.update({key: [value] * n for key, value in time_columns.items()})
        columns.update({key: pa.array(value.ravel(), from_pandas=True) for key, value in values.items()})
        return pa.table({key: columns[key] for key in tables[name]["columns"]})

    with ExitStack() as stack:
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
                progress("M2 日和候预处理", f"{year}-{month:02d}",
                         ((year - first) * 12 + month - 1) / ((last - first + 1) * 12))
                raw = load(monthly[year, month, "instant"], FIELDS["instant"], slice(None))
                scale = settings["mm_per_m"]
                root_soil = sum(raw[f"swvl{i}"] * thickness
                                for i, thickness in enumerate(settings["root_layer_thickness_m"], 1))
                shape = (-1, 24, *root_soil.shape[1:])
                values = {"sm_0_100_mm": root_soil.reshape(shape).mean(axis=1) * scale,
                          "sm_deep_mm": raw["swvl4"].reshape(shape).mean(axis=1)
                          * settings["deep_layer_thickness_m"] * scale,
                          "t2m_c": raw["t2m"].reshape(shape).mean(axis=1) - settings["kelvin_offset"]}
                del raw, root_soil
                next_year, next_month = year + (month == 12), month % 12 + 1
                for group in ("accumulated", "runoff_components"):
                    fields = FIELDS[group]
                    path = monthly.get((next_year, next_month, group), terminal)
                    midnight = load(path, fields, slice(0, 1))
                    raw = load(monthly[year, month, group], fields, slice(None))
                    for field in fields:
                        values[FLUX_NAMES[field]] = daily_flux(field, raw[field], midnight[field][0], settings)
                    del raw
                values["runoff_mm"] = values["runoff_surface_mm"] + values["runoff_subsurface_mm"]
                values["balance_mm"] = values["p_mm"] - values["et_loss_mm"] - values["runoff_mm"]
                n_days = len(values["p_mm"])
                for field, array in values.items():
                    if field not in daily:
                        daily[field] = np.empty((year_days, *array.shape[1:]), dtype=float)
                    daily[field][day_offset:day_offset + n_days] = array
                for index in range(n_days):
                    day = date(year, month, index + 1)
                    write("grid_day", batch("grid_day", {key: value[index] for key, value in values.items()},
                                            {"date": day}))
                day_offset += n_days
            for row in calendar[(year - first) * params["time"]["pentads_per_year"]:
                                (year - first + 1) * params["time"]["pentads_per_year"]]:
                start = (row["start_date"] - date(year, 1, 1)).days
                values = aggregate_pentad({name: array[start:start + row["n_days"]]
                                          for name, array in daily.items()}, params["time"])
                keys = ("t_abs", "year", "pentad", "start_date", "end_date", "n_days")
                write("grid_pentad_base", batch("grid_pentad_base", values, {key: row[key] for key in keys}))
