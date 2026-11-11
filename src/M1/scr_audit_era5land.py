"""脚本名：scr_audit_era5land.py（M1 · ERA5-Land 原始验收）
功能简介：校验原生字段、UTC 小时轴、网格、数据范围和来源登记。
作者：Codex
版本：v0.1.0
读取数据：原始月文件、冻结参数和边界、机器本地来源登记。
生成数据：文件级验收、变量映射与缺项记录，由统一入口发布。
其他文件：审计日志由编排层管理。
运行示例：python -m workflow.run_module M1 --run-alias 2026-11-10_主分析
退出码：由统一入口定义。
"""
from datetime import datetime, timedelta
from hashlib import file_digest, sha256
from pathlib import Path

FIELDS = {
    "instant": ("swvl1", "swvl2", "swvl3", "swvl4", "t2m"),
    "accumulated": ("tp", "e", "pev"),
    "runoff_components": ("sro", "ssro"),
}
CANONICAL = {
    "swvl1": "sm_l1_m3m3", "swvl2": "sm_l2_m3m3", "swvl3": "sm_l3_m3m3",
    "swvl4": "sm_l4_m3m3", "t2m": "t2m_c", "tp": "p_mm",
    "e": "et_loss_mm", "pev": "pet_loss_mm", "sro": "runoff_surface_mm",
    "ssro": "runoff_subsurface_mm",
}
PRODUCT = "era5land"
CUMULATIVE = "forecast_step_cumulative"


def digest(path, advance=None):
    """流式计算文件 SHA-256。"""
    with path.open("rb") as source:
        if advance is None:
            return file_digest(source, "sha256").hexdigest()
        checksum = sha256()
        while chunk := source.read(4 * 2**20):
            checksum.update(chunk)
            advance(len(chunk))
        return checksum.hexdigest()


def era5land_years(params):
    """返回事件、气候态和背景协变量所需的原始年份范围。"""
    first = min(params["time"]["year_start"], params["clim"]["base_window"][0],
                params["covariates"]["climate_years"][0])
    return first, params["time"]["year_end"]


def expected_files(settings, first, last):
    """按批次列出月文件和末日结算补档。"""
    for year in range(first, last + 1):
        for month in range(1, 13):
            start = datetime(year, month, 1)
            stop = datetime(year + (month == 12), month % 12 + 1, 1)
            for group, fields in FIELDS.items():
                kind = "instant" if group == "instant" else "accumulated"
                path = Path(settings["raw_root"]) / "era5_land" / group / (
                    f"ERA5-Land_{kind}_{year}_{month:02d}.nc"
                )
                yield path, group, fields, start, stop
    start = datetime(last + 1, 1, 1)
    path = Path(settings["raw_root"]) / "era5_land/accumulated" / (
        f"ERA5-Land_accumulated_{last + 1}_01.nc"
    )
    yield path, "accumulated", (*FIELDS["accumulated"], *FIELDS["runoff_components"]), start, start + timedelta(hours=1)


def native_axes(dataset):
    """读取标准日历的 UTC 有效时间和规则经纬坐标。"""
    from netCDF4 import num2date
    import numpy as np

    time_name = "valid_time" if "valid_time" in dataset.variables else "time"
    axis = dataset[time_name]
    if axis.dimensions != (time_name,) or axis.getncattr("units").endswith(" local"):
        raise ValueError("时间坐标不是一维有效时间。")
    dates = num2date(axis[:], axis.units, getattr(axis, "calendar", "standard"),
                     only_use_cftime_datetimes=False, only_use_python_datetimes=True)
    if np.ma.getmaskarray(dates).any():
        raise ValueError("时间坐标含缺测。")
    coords = []
    for name in ("latitude", "longitude"):
        variable = dataset[name]
        values = variable[:]
        if variable.dimensions != (name,) or np.ma.getmaskarray(values).any():
            raise ValueError(f"{name} 坐标非法。")
        coords.append(np.asarray(values, dtype=float))
    return time_name, list(dates), *coords


def read_field(dataset, name, time_name, selection, latitude=slice(None), longitude=slice(None)):
    """按时间、纬度、经度顺序解码变量，缺测保留为 NaN。"""
    import numpy as np

    variable = dataset[name]
    dimensions = (time_name, "latitude", "longitude")
    if len(variable.dimensions) != 3 or set(variable.dimensions) != set(dimensions):
        raise ValueError(f"{name} 有未经支持的维度：{variable.dimensions}")
    selections = dict(zip(dimensions, (selection, latitude, longitude)))
    index = tuple(selections[axis] for axis in variable.dimensions)
    values = np.ma.asarray(variable[index], dtype=np.float64).filled(np.nan)
    if np.isinf(values).any():
        raise ValueError(f"{name} 有无穷值。")
    return values.transpose([variable.dimensions.index(axis) for axis in dimensions])


def inspect_file(path, fields, start, stop, params, bbox, reference):
    """验证完整月轴或补档首时次，分日扫描原生数据与处理步累计。"""
    from netCDF4 import Dataset
    import numpy as np

    settings = params["native_era5land"]
    tolerance = settings["water_roundoff_m"]
    west, south, east, north = bbox
    with Dataset(path) as dataset:
        time_name, dates, lat, lon = native_axes(dataset)
        required = int((stop - start) / timedelta(hours=1))
        expected = [start + timedelta(hours=i) for i in range(required)]
        if dates[:required] != expected or (required > 1 and len(dates) != required):
            raise ValueError("小时坐标有缺口、重复或不属于登记月份。")
        if required == 1 and any(b - a != timedelta(hours=1) for a, b in zip(dates, dates[1:])):
            raise ValueError("补档时间坐标不连续。")
        if "expver" in dataset.variables:
            version = dataset["expver"]
            values = version[...] if version.ndim == 0 else version[:required]
            if np.ma.getmaskarray(values).any() or any(
                    str(value).strip() not in {"1", "0001"} for value in np.asarray(values).ravel()):
                raise ValueError("expver 包含非正式生产流或缺失版本。")
        resolution = params["grid"]["resolution_deg"]
        for coord, low, high in ((lat, south, north), (lon, west, east)):
            differences = np.diff(coord)
            if (not np.isfinite(coord).all() or not len(differences)
                    or not (np.all(differences > 0) or np.all(differences < 0))
                    or not np.allclose(abs(differences), resolution, atol=1e-5)
                    or coord.min() - resolution / 2 > low + 1e-5
                    or coord.max() + resolution / 2 < high - 1e-5):
                raise ValueError("经纬度方向、分辨率或研究区覆盖异常。")
        if reference is not None and not all(np.array_equal(np.sort(a), np.sort(b))
                                             for a, b in zip(reference, (lat, lon))):
            raise ValueError("原生批次网格不一致。")
        half = resolution / 2
        iy = np.flatnonzero((lat + half > south) & (lat - half < north))
        ix = np.flatnonzero((lon + half > west) & (lon - half < east))
        native = {}
        for name in fields:
            var = dataset[name]
            unit = str(getattr(var, "units", "")).strip()
            if name.startswith("swvl"):
                allowed, bounds = {"m**3 m**-3", "m3 m-3", "m3/m3", "m³/m³", "1"}, (0, 1)
            elif name == "t2m":
                allowed, bounds = {"K"}, settings["temperature_range_k"]
            else:
                allowed = {"m", "m of water equivalent"}
                bounds = (-tolerance, np.inf) if name in {"tp", "sro", "ssro"} else (-np.inf, np.inf)
            if unit not in allowed:
                raise ValueError(f"{name} 单位未获支持：{unit}")
            minimum, maximum = np.inf, -np.inf
            has_step_increase = False
            first_value = last_value = None
            cumulative = name in {"tp", "sro", "ssro"}
            bytes_per_day = 24 * len(lat) * len(lon) * np.dtype(np.float64).itemsize
            hours_per_batch = 24 * max(1, (96 * 2**20) // bytes_per_day)
            for offset in range(0, required, hours_per_batch):
                values = read_field(dataset, name, time_name,
                                    slice(offset, min(required, offset + hours_per_batch)))
                values = values[:, iy[0]:iy[-1] + 1, ix[0]:ix[-1] + 1]
                valid = values[np.isfinite(values)]
                if valid.size:
                    minimum = min(minimum, valid.min())
                    maximum = max(maximum, valid.max())
                if first_value is None:
                    first_value = values[0].copy()
                if cumulative and required > 1:
                    daily = values.reshape(-1, 24, *values.shape[1:])
                    increments = np.diff(daily[:, 1:], axis=1)
                    endpoint = daily[1:, 0] - daily[:-1, -1]
                    boundary = values[0] - last_value if last_value is not None else endpoint[:0]
                    checks = (increments, endpoint, boundary)
                    if any(np.any(check < -tolerance) for check in checks):
                        raise ValueError(f"{name} 在同一预报日内回落，累计语义待查。")
                    has_step_increase |= any(np.any(check > tolerance) for check in checks)
                last_value = values[-1].copy()
            if minimum == np.inf:
                raise ValueError(f"{name} 审计窗口全缺测。")
            if minimum < bounds[0] or maximum > bounds[1]:
                raise ValueError(f"{name} 超出原生物理范围。")
            native[name] = {"unit": unit, "scale_factor": str(getattr(var, "scale_factor", 1)),
                            "add_offset": str(getattr(var, "add_offset", 0)),
                            "fill_value": str(getattr(var, "_FillValue", getattr(var, "missing_value", ""))),
                            "step_increase": has_step_increase, "negative": bool(minimum < -tolerance)}
            if cumulative:
                order = np.ix_(np.argsort(lat[iy]), np.argsort(lon[ix]))
                native[name]["first"] = first_value[order]
                native[name]["last"] = last_value[order]
        extent = [float(lon.min()), float(lat.min()), float(lon.max()), float(lat.max())]
        return native, (lat, lon), extent, (dates[0], dates[required - 1])


def audit_file(task):
    """在独立进程内计算文件哈希和原生 QC，保留失败前已取得的证据。"""
    path, fields, start, stop, params, bbox, raw_root = task
    size = checksum = inspected = error = None
    try:
        if not path.is_file():
            raise FileNotFoundError("原始文件缺失。")
        if not path.resolve().is_relative_to(raw_root):
            raise ValueError("原始文件路径越过登记根目录。")
        before = path.stat()
        size = before.st_size
        checksum = digest(path)
        inspected = inspect_file(path, fields, start, stop, params, bbox, None)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("文件在验收期间发生变化。")
    except (OSError, ValueError, KeyError, RuntimeError) as failure:
        error = failure
    return size, checksum, inspected, error


def audit_era5land(root, params, bbox, evidence, progress, runtime=None):
    """逐月审计现有 NetCDF。只有原生与下载证据都齐全时放行 ERA5-Land。"""
    settings = params["native_era5land"]
    first, last = era5land_years(params)
    entries = list(expected_files(settings, first, last))
    files, checks, maps, missing = [], [], {}, []
    reference = None
    import numpy as np
    from workflow.runtime import ordered_tasks, resolve_runtime
    from workflow.progress import emit

    step_fields, negative_fields = set(), set()
    prior = {}
    tolerance = settings["water_roundoff_m"]
    raw_root = (root / settings["raw_root"]).resolve()
    tasks = ((root / relative, fields, start, stop, params, bbox, raw_root)
             for relative, _, fields, start, stop in entries)
    results = ordered_tasks(audit_file, tasks, runtime or resolve_runtime({"profile": "low"}),
                            task_gib=0.5, reads_disk=True)
    for index, ((relative, group, fields, start, stop), result) in enumerate(zip(entries, results)):
        key = "terminal" if stop - start == timedelta(hours=1) else group
        batch = evidence.get(key, {})
        if not isinstance(batch, dict):
            raise ValueError(f"来源登记 {key} 须为映射。")
        row = {"file_id": relative.as_posix(), "file_path": relative.as_posix(),
               "product_code": PRODUCT, "native_variable_names": ",".join(fields),
               "time_start": start.isoformat(), "time_end": (stop - timedelta(hours=1)).isoformat()}
        check = {"source_id": row["file_id"], "product_code": PRODUCT}
        failure_status = "failed"
        try:
            size, checksum, inspected, error = result
            if size is not None:
                row["file_size_bytes"] = size
            if checksum is not None:
                row["sha256"] = check["file_sha256"] = checksum
            if error is not None:
                raise error
            native, coords, extent, dates = inspected
            if reference is not None and not all(np.array_equal(np.sort(a), np.sort(b))
                                                 for a, b in zip(reference, coords)):
                raise ValueError("原生批次网格不一致。")
            if reference is None:
                reference = coords
            for name in ("tp", "sro", "ssro"):
                if name not in native:
                    continue
                if name in prior and prior[name][0] == start:
                    if np.any(native[name]["first"] - prior[name][1] < -tolerance):
                        raise ValueError(f"{name} 跨月第 24 步累计回落。")
                prior[name] = (stop, native[name]["last"])
            row.update({"time_start": dates[0].isoformat(), "time_end": dates[1].isoformat(),
                        "spatial_extent": str(extent), "native_resolution": params["grid"]["resolution_deg"],
                        "crs": "OGC:CRS84", "time_zone": "UTC", "timestamp_meaning": "有效时间",
                        "lat_direction": "ascending" if coords[0][0] < coords[0][-1] else "descending",
                        "lon_direction": "ascending" if coords[1][0] < coords[1][-1] else "descending",
                        "accumulation_type": "instant" if group == "instant" else CUMULATIVE,
                        "unit_source": str({n: v["unit"] for n, v in native.items()})})
            for column in ("scale_factor", "add_offset", "fill_value"):
                row[column] = str({n: v[column] for n, v in native.items()})
            check.update(dict.fromkeys(("variable_check", "dimension_check", "coordinate_check",
                                        "time_check", "unit_check", "fill_check", "physical_range_check"), "passed"))
            check["qc_decode_check"] = "not_applicable"
            for name in ("collection_version", "download_date", "request_id", "source_url",
                         "license", "access_status"):
                row[name] = batch.get(name, "")
            check["collection"] = row["collection_version"]
            failure_status = "pending"
            if (row["access_status"] != "allowed" or not all(row[n] for n in ("collection_version", "download_date", "license", "access_status"))
                    or not (row["request_id"] or row["source_url"]) or not batch.get("reviewer")
                    or not batch.get("verification_date") or batch.get("time_zone") != "UTC"
                    or batch.get("timestamp_meaning") != "valid_time"
                    or batch.get("production_stream") != "consolidated"
                    or (group != "instant" and batch.get("accumulation_type") != CUMULATIVE)
                    or ("e" in fields and batch.get("evaporation_sign") != "upward_negative")):
                raise ValueError("缺正式下载来源、时间或累计符号的人工核验登记。")
            check.update(reviewer=batch["reviewer"], accepted_at_utc=batch["verification_date"])
            for name, details in native.items():
                mapping_id = f'{PRODUCT}:{row["collection_version"]}:{name}:{details["unit"]}'
                if details["step_increase"]:
                    step_fields.add(name)
                if details["negative"]:
                    negative_fields.add(name)
                maps[mapping_id] = {"mapping_id": mapping_id, "product_code": PRODUCT,
                    "collection_version": row["collection_version"], "native_variable_name": name,
                    "canonical_field": CANONICAL[name], "native_unit": details["unit"],
                    "canonical_unit": "degC" if name == "t2m" else ("m3/m3" if name.startswith("swvl") else "mm"),
                    "scale_factor": details["scale_factor"], "add_offset": details["add_offset"],
                    "sign_rule": "negate" if name in {"e", "pev"} else "identity",
                    "accumulation_type": row["accumulation_type"], "metadata_source": row["source_url"] or row["request_id"],
                    "verified_by": batch["reviewer"], "verification_date": batch["verification_date"],
                    "mapping_status": "accepted"}
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            row.update(audit_status="pending" if isinstance(error, FileNotFoundError) else failure_status,
                       audit_note=str(error))
            missing.append({"product_code": PRODUCT, "period": start.date().isoformat(),
                            "file_path": relative.as_posix(), "reason": str(error)})
        else:
            row["audit_status"] = "accepted"
        check.update(acceptance_status=row["audit_status"], failed_items=row.get("audit_note", ""))
        files.append(row)
        checks.append(check)
        emit(progress, "M1", "原始数据验收", relative.name, done=index + 1, total=len(entries), unit="文件")
    if not missing and (not {"tp", "sro", "ssro"} <= step_fields or not {"e", "pev"} <= negative_fields):
        missing.append({"product_code": PRODUCT, "period": "", "file_path": "",
                        "reason": "未找到非零处理步累计或向上为负的蒸发实值证据。"})
    if missing:
        for mapping in maps.values():
            mapping["mapping_status"] = "pending"
    return files, checks, list(maps.values()), missing
