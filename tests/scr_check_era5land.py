"""脚本名：scr_check_era5land.py（测试 · M1/M2）
功能简介：用微型原生文件验证验收、冻结交接和水量换算。
作者：Codex
版本：v0.1.0
读取数据：测试夹具和项目配置。
生成数据：pytest 临时目录中的 NetCDF 和 Parquet。
其他文件：无。
运行示例：python -m pytest tests/scr_check_era5land.py
退出码：由 pytest 定义。
"""
from datetime import date
import json
from pathlib import Path
from shutil import copytree

from netCDF4 import Dataset
import numpy as np
import pyarrow.parquet as pq
import pytest
import yaml

from src.M1.scr_audit_era5land import digest, expected_files
from src.M2.scr_prepare_era5land import FLUX, STATE, aggregate_pentad, daily_flux, pentad_calendar
from workflow import run_module as runner


def test_sop_day_boundary_and_missing():
    """E1/E2/U3 验证日界、符号与缺日传播。"""
    settings = runner.load_config(runner.DEFAULT_CONFIG)
    raw = np.arange(24, dtype=float)[:, None] * 0.0002
    raw[0] = 0.008
    assert daily_flux("tp", raw, np.array([0.005]), settings["native_era5land"])[0, 0] == 5
    evaporation = -raw.copy()
    assert daily_flux("e", evaporation, np.array([-0.003]), settings["native_era5land"])[0, 0] == 3
    raw[13] = np.nan
    assert np.isnan(daily_flux("tp", raw, np.array([0.005]), settings["native_era5land"])[0, 0])
    days = {name: np.ones((6, 2)) for name in (*FLUX, *STATE)}
    for field in STATE:
        days[field][1:3, 0] = np.nan
        days[field][1:4, 1] = np.nan
    days["p_mm"][1, 0] = np.nan
    result = aggregate_pentad(days, settings["time"])
    assert result["sm_0_100_mm"][0] == 1
    assert np.isnan(result["sm_0_100_mm"][1])
    assert np.isnan(result["p_mm"][0])
    assert result["p_mm"][1] == 6
    assert result["p_5day_equivalent_mm"][1] == 5


def write_native(path, fields, start, count):
    """构造两行两列的 UTC 小时 NetCDF。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with Dataset(path, "w") as dataset:
        dataset.createDimension("valid_time", count)
        dataset.createDimension("latitude", 2)
        dataset.createDimension("longitude", 2)
        time = dataset.createVariable("valid_time", "i4", ("valid_time",))
        time.units = f"hours since {start:%Y-%m-%d} 00:00:00"
        time[:] = np.arange(count)
        dataset.createVariable("latitude", "f8", ("latitude",))[:] = [34.1, 34]
        dataset.createVariable("longitude", "f8", ("longitude",))[:] = [103, 103.1]
        for name in fields:
            variable = dataset.createVariable(name, "f8", ("valid_time", "latitude", "longitude"))
            if name.startswith("swvl"):
                variable.units = "m3/m3"
                variable[:] = int(name[-1]) / 10
            elif name == "t2m":
                variable.units = "K"
                variable[:] = 293.15
            else:
                variable.units = "m"
                step = (np.arange(count) - 1) % 24 + 1
                sign = -1 if name in {"e", "pev"} else 1
                variable[:] = (sign * step / 24000)[:, None, None]


def test_m0_m1_m2_handoff(tmp_path, monkeypatch):
    """验证合成闰年贯通、E3/E4 数值、Parquet 键与原始哈希阻断。"""
    original = runner.ROOT
    for name in ("config", "metadata", "docs", "workflow"):
        copytree(original / name, tmp_path / name,
                 ignore=lambda _, names: {"local", "__pycache__"}.intersection(names))
    config_path = tmp_path / "config/params.yaml"
    params = runner.load_config(config_path)
    params["time"].update(year_start=2015, year_end=2020)
    params["clim"]["base_window"] = params["covariates"]["climate_years"] = [2015, 2020]
    params["lai"]["complete_years"] = [2015, 2020]
    params["lai"]["exposure_years"] = params["ndvi"]["common_sample_years"] = [2020, 2020]
    config_path.write_text(yaml.safe_dump(params, allow_unicode=True), encoding="utf-8")
    # 隔离测试保留真实的 M0 边界验收，再为微型网格替换运行边界。
    from workflow import run_era5land
    frozen_context = run_era5land.frozen_context

    def synthetic_context(*args):
        record, identity, output, logs, _ = frozen_context(*args)
        return record, identity, output, logs, [103, 34, 103.1, 34.1]

    monkeypatch.setattr(run_era5land, "frozen_context", synthetic_context)
    monkeypatch.setattr(run_era5land.subprocess, "check_output", lambda *a, **k: "a" * 40)
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    entries = list(expected_files(params["native_era5land"], 2015, 2020))
    for path, _, fields, start, stop in entries:
        write_native(tmp_path / path, fields, start, int((stop - start).total_seconds() // 3600))
    evidence = {"collection_version": "fixture", "download_date": "2026-11-10", "license": "fixture",
                "access_status": "allowed", "request_id": "fixture", "reviewer": "fixture",
                "verification_date": "2026-11-10", "time_zone": "UTC", "timestamp_meaning": "valid_time",
                "production_stream": "consolidated", "accumulation_type": "forecast_step_cumulative",
                "evaporation_sign": "upward_negative"}
    local = tmp_path / params["native_era5land"]["evidence"]
    local.parent.mkdir(parents=True)
    local.write_text(yaml.safe_dump({key: evidence for key in
                                    ("instant", "accumulated", "runoff_components", "terminal")}),
                     encoding="utf-8")
    options = {"config_path": config_path, "run_alias": "2026-11-10_合成验证"}
    assert runner.run_module("M0", freeze=True, **options)["m0_audit"]["formal_freeze_written"]
    outcome = runner.run_module("M2", **options)
    assert outcome["module_status"] == {"M1": "passed", "M2": "passed"}
    out = Path(outcome["m2_interim"])
    table = pq.read_table(out / "grid_pentad_base_era5land.parquet")
    assert table.num_rows == 6 * 73 * 4
    row = table.slice(table.num_rows - 4, 1).to_pylist()[0]
    assert row["start_date"] == date(2020, 12, 26)
    assert row["n_days"] == 6 and row["p_mm"] == pytest.approx(6)
    assert row["et_loss_mm"] == pytest.approx(6)
    assert row["sm_0_100_mm"] == pytest.approx(265)
    assert row["sm_deep_mm"] == pytest.approx(756)
    assert row["balance_mm"] == pytest.approx(-12)
    assert pq.ParquetFile(out / "grid_day_era5land.parquet").metadata.num_rows == (date(2021, 1, 1) - date(2015, 1, 1)).days * 4
    assert runner.run_module("M2", **options)["module_status"] == outcome["module_status"]
    support = tmp_path / "data/interim/synthetic_support.json"
    grid = pq.read_table(out / "grid_manifest.parquet").to_pylist()
    support.write_text(json.dumps([
        dict(grid_id=cell["grid_id"], vegetation_area_frac=0.9, native_exclude_frac=0,
             valid_landcover_years=20, baseline_land_cover="forest",
             phenology=[dict(year=y, valid_pixel_area_frac=1, valid_native_pixels=100,
                             segments=[[f"{y}-04-01", f"{y}-09-30"]]) for y in range(2015, 2021)])
        for cell in grid]), encoding="utf-8")
    manifest = tmp_path / params["downstream"]["supplement_manifest"]
    manifest.write_text(json.dumps({"grid_support": {
        "status": "accepted", "path": support.relative_to(tmp_path).as_posix(), "sha256": digest(support),
        "sources": [{"path": entries[0][0].as_posix(), "sha256": digest(tmp_path / entries[0][0])}],
    }}), encoding="utf-8")
    route1 = runner.run_module("route1", **options)
    assert route1["module_status"]["M3"] == "passed"
    assert route1["module_status"]["M10"] == "descriptive_only"
    figures = tmp_path / "outputs" / options["run_alias"] / "figures"
    figure_manifest = json.loads((figures / "figure_manifest.json").read_bytes())
    assert len(figure_manifest) == 7 and all(item["status"] == "omitted" for item in figure_manifest)
    assert "M8" not in route1["module_status"]
    full = runner.run_module("full", **options)
    assert full["module_status"]["M8"] == "exited"
    assert full["module_status"]["M10"] == "descriptive_only"
    support.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="哈希不符"):
        runner.run_module("full", **options)
    with (tmp_path / entries[0][0]).open("ab") as raw:
        raw.write(b"changed")
    with pytest.raises(ValueError, match="原始文件哈希"):
        runner.run_module("M2", **options)


def test_calendar_continuity():
    """U1 检查平闰年余日与跨年连续键。"""
    rows = pentad_calendar(2019, 2020, 73, 2000)
    assert rows[0]['t_abs'] == 19 * 73 + 1
    assert [rows[index]["n_days"] for index in (72, 145)] == [5, 6]
    assert rows[72]["next_t_abs"] == rows[73]["t_abs"]
    assert rows[73]["previous_t_abs"] == rows[72]["t_abs"]
    assert rows[-1]["next_t_abs"] is None
