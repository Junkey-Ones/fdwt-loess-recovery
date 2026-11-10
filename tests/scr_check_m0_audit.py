"""脚本名：scr_check_m0_audit.py（测试 · M0 冻结前审计）

功能简介：核对预注册参数锚点和隔离环境下的审计入口。
作者：Codex
版本：v0.1.0
读取数据：仓库配置、登记与协议文档。
生成数据：pytest 临时目录内的审计日志。
其他文件：无。
运行示例：python -m pytest tests/scr_check_m0_audit.py
退出码：由 pytest 定义。
"""
from hashlib import sha256
import json
from pathlib import Path
from shutil import copytree

import pytest

from workflow import freeze_m0
import workflow.run_module as runner


def test_preregistered_parameters():
    """按预注册 §§2、3、7.3 核对发布配置中的时期、锚点和检验家族。"""
    params = runner.load_config(runner.DEFAULT_CONFIG)
    assert [params["time"]["year_start"], params["time"]["year_end"]] == [2003, 2023]
    assert params["clim"]["base_window"] == [2003, 2023]
    assert params["lai"]["complete_years"] == [2003, 2023]
    assert params["lai"]["exposure_years"] == params["ndvi"]["common_sample_years"] == [2008, 2023]
    assert params["lai"]["window_years"] == params["lai"]["main_requires_full"] == 5
    assert params["route1"]["recovery_risk_t0"] == "t_min"
    assert params["route2"]["t0"] == "t_s"
    assert params["drought"]["min_duration_pentads"] == 4
    assert params["recovery"]["terminate_smp"] == 20
    assert params["fr"]["window"] == ["t_e-1", "t_e+1"]
    assert params["pterm"]["window"] == ["t_min", "t_e+2"]
    assert params["fr"]["h1_uses"] == ["pre", "sync"]
    assert params["fr"]["percentile"] == params["pterm"]["percentile"] == 95
    assert params["fr"]["min_p_mm"] == params["pterm"]["min_p_mm"] == 1
    tests = params["multiple_testing"]
    assert tests["family_adjustment"] == "holm"
    assert tests["family_alpha"] == tests["map_bh_q"] == 0.05
    assert tests["families"] == {
        "q1": ["annual_rt_trend", "annual_delta_smp_trend", "annual_rr_trend"],
        "q2": ["fr_pre_sync_rr_contrast", "fr_pre_sync_delta_smp_contrast"],
        "q3": ["lai_trend_recovery_risk", "lai_trend_fr",
               "lai_trend_deep_recovery_risk", "lai_trend_deep_fr"],
    }


@pytest.fixture
def isolated_repo(tmp_path, monkeypatch):
    """提供隔离的协议、登记及工作流副本。"""
    for directory in ("config", "metadata", "docs", "workflow"):
        copytree(runner.ROOT / directory, tmp_path / directory,
                 ignore=lambda _, names: {"local", "__pycache__"}.intersection(names))
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    return tmp_path


def test_audit_retry(isolated_repo):
    """构造主键缺列，验证阻断、证据哈希和重跑日志隔离。"""
    tmp_path = isolated_repo
    schema_path = tmp_path / "config" / "schema_registry.yaml"
    with schema_path.open("a", encoding="utf-8") as schema:
        schema.write("\n  test_missing_key:\n    columns: [value]\n    primary_key: [id]\n")
    params_path = tmp_path / "config" / "params.yaml"
    options = {"config_path": params_path, "run_alias": "2026-11-10_测试"}
    assert runner.run_module("M0", dry_run=True, **options)["modules"] == ["M0"]
    assert not (tmp_path / "logs").exists()
    first = runner.run_module("M0", **options)
    path = Path(first["audit_log"])
    first_log = path.read_bytes()
    second = runner.run_module("M0", **options)
    assert first["audit_log"] != second["audit_log"]
    assert path.read_bytes() == first_log
    report = first["m0_audit"]
    assert report == second["m0_audit"] == json.loads(first_log)["stdout"]
    assert report["status"] == "failed"
    assert not report["formal_freeze_written"] and not report["regional_release"]
    assert first["run_id"] is None
    assert report["input_sha256"]["config/params.yaml"] == sha256(params_path.read_bytes()).hexdigest()
    checks = {row["check_id"]: row["status"] for row in report["checks"]}
    assert checks["schema_test_missing_key"] == "failed"
    assert checks["research_boundary"] == "passed"
    assert checks["random_seed"] == "passed"
    assert not (tmp_path / "outputs").exists()
    with pytest.raises(ValueError, match="不能绑定正式"):
        runner.run_module("M0", run_id="test_run", **options)
    boundary_path = tmp_path / "metadata" / "study_area_rectangle.geojson"
    with boundary_path.open("ab") as boundary:
        boundary.write(b"\n")
    changed = runner.run_module("M0", **options)["m0_audit"]
    checks = {row["check_id"]: row["status"] for row in changed["checks"]}
    assert checks["research_boundary"] == "failed"


def test_freeze_retry(isolated_repo, monkeypatch):
    """验证首次登记、幂等续跑及参数变更时保护已冻结内容。"""
    monkeypatch.setattr(freeze_m0.subprocess, "check_output", lambda *args, **kwargs: "a" * 40)
    params = isolated_repo / "config/params.yaml"
    options = {"config_path": params, "run_alias": "2026-11-10_M0", "freeze": True}
    first = runner.run_module("M0", **options)
    frozen = Path(first["freeze_record"])
    original = frozen.read_bytes()
    index = isolated_repo / "metadata/run_index.csv"
    registered = index.read_bytes()
    assert first["m0_audit"]["formal_freeze_written"]
    assert first["run_id"] == json.loads(original)["run_id"]
    assert first["run_id"] in registered.decode("utf-8")
    receipt = isolated_repo / "logs/2026-11-10_M0/module_io_M0.json"
    receipt.unlink()
    assert runner.run_module("M0", **options)["run_id"] == first["run_id"]
    assert receipt.exists()
    with pytest.raises(ValueError, match="别名已登记"):
        runner.run_module("M0", resume=False, **options)
    with params.open("ab") as handle:
        handle.write(b"\n")
    with pytest.raises(ValueError, match="别名已登记"):
        runner.run_module("M0", **options)
    assert frozen.read_bytes() == original and index.read_bytes() == registered
