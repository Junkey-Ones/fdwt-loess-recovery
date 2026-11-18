"""空间规则修订的合成回归测试，不读取真实暴露—结局效应。

运行：python -m pytest tests/scr_check_spatial_inference.py。
"""
from copy import deepcopy

import numpy as np
import pytest

from workflow.run_module import DEFAULT_CONFIG, load_config
from src.M5.scr_group_wet_processes import build_superblocks
from src.M7.scr_spatial_inference import resampling_label, resampling_scheme
from src.M7.scr_fit_route1_models import fit_one_model, lag_intervals, summarize_fr_support


def test_cross_year_chain_is_diagnostic_only():
    """不同年份桥接三个块：保留一个连接诊断，但新方案抽样仍为三个块。"""
    p = load_config(DEFAULT_CONFIG)
    grids = [dict(grid_id=x, block_id=x) for x in "abc"]
    events = [dict(grid_id=g, cluster_id=c, year=y) for g, c, y in
              [("a", "r1", 2008), ("b", "r1", 2008), ("b", "r2", 2020), ("c", "r2", 2020)]]
    joined = {r["block_id"]: r["superblock_id"] for r in build_superblocks(events, grids)}
    assert len(set(joined.values())) == 1
    assert {resampling_label(b, joined, p) for b in "abc"} == set("abc")
    old = deepcopy(p)
    del old["block"]["resampling_unit"]
    assert len({resampling_label(b, joined, old) for b in "abc"}) == 1
    with pytest.raises(ValueError, match="缺少超级块"):
        resampling_label("d", joined, old)
    p["block"]["resampling_unit"] = "unknown"
    with pytest.raises(ValueError, match="空间抽样"):
        resampling_scheme(p)


def test_descriptive_intervals_use_fixed_blocks():
    """已合并的诊断图不阻断固定块描述区间，方法标签与旧规则有区别。"""
    p = load_config(DEFAULT_CONFIG)
    p["block"]["bootstrap_n"] = 20
    blocks = {str(i): str(i) for i in range(24)}
    merged = {b: "all" for b in blocks.values()}
    events = [dict(grid_id=str(i), year=2010, route1_A_eligible=True,
                   route1_FR_eligible=True, F_R=True, P_term=True, Lag_FR=i % 3 + 1)
              for i in range(24)]
    _, results = summarize_fr_support(events, blocks, merged, p)
    region = next(r for r in results if r["domain"] == "region")
    assert (region["n_superblock"], region["n_resampling_block"]) == (1, 24)
    assert region["ci_low"] == region["ci_high"] == 1
    assert region["ci_method"] == "fixed_space_bootstrap"
    lag = [dict(metric="Lag_FR", n_event=24)]
    lag_intervals(events, lag, blocks, merged, p)
    assert lag[0]["ci_low"] is not None and lag[0]["n_resampling_block"] == 24
    p["block"]["resampling_unit"] = "superblock"
    _, results = summarize_fr_support(events, blocks, merged, p)
    assert next(r for r in results if r["domain"] == "region")["ci_low"] is None


def test_synthetic_model_unblocked_without_lowering_gate():
    """合成模型新规则通过原支撑门槛，旧规则仍因单超级块退出。"""
    p = load_config(DEFAULT_CONFIG)
    p["block"]["bootstrap_n"] = 20
    rng = np.random.default_rng(1234)
    blocks = {str(i): str(i) for i in range(24)}
    merged = {b: "all" for b in blocks.values()}
    rows = [dict(episode_id=f"{b}:{y}", grid_id=b, year=y,
                 product="synthetic", definition_id="test", support_id="test",
                 deep_SM_pre4_percentile=float(rng.normal()), F_R=bool(rng.integers(2)))
            for b in blocks for y in range(2008, 2024)]
    spec = ("q3_fr_D", "Q3", "logit", "F_R", ["deep_SM_pre4_percentile"], rows, None)
    manifests, coefficients, marginal, uncertainty = [], [], [], []
    fit_one_model(spec, {}, [], blocks, merged, p, {}, manifests, coefficients, marginal, uncertainty)
    assert manifests[0]["support_gate"] == "passed"
    assert manifests[0]["n_superblock"] == 1
    assert manifests[0]["n_resampling_block"] == 24
    assert manifests[0]["n_year"] == 16
    assert manifests[0]["n_eff"] == 24
    assert {r["ci_method"] for r in uncertainty} == {"fixed_space_bootstrap", "block_year"}
    p["block"]["resampling_unit"] = "superblock"
    old = []
    fit_one_model(spec, {}, [], blocks, merged, p, {}, old, [], [], [])
    assert old[0]["support_gate"] == "insufficient_support"
    assert old[0]["convergence_status"] == "not_attempted"


def test_rare_category_bootstrap_failure_is_reported():
    """单块地类导致自举秩亏时保留点估计，并明确报告失败而非正式放行。"""
    import json
    p = load_config(DEFAULT_CONFIG)
    p["block"]["bootstrap_n"] = 100
    rng = np.random.default_rng(321)
    blocks = {str(i): str(i) for i in range(24)}
    rows = [dict(episode_id=f"{b}:{y}", grid_id=b, year=y,
                 product="synthetic", definition_id="test", support_id="test",
                 land_cover="forest" if b == "0" else "grassland",
                 deep_SM_pre4_percentile=float(rng.normal()), F_R=bool(rng.integers(2)))
            for b in blocks for y in range(2008, 2024)]
    spec = ("q3_fr_D", "Q3", "logit", "F_R", ["deep_SM_pre4_percentile"], rows, None)
    manifest, updates = [], []
    fit_one_model(spec, {}, ["land_cover"], blocks, {}, p, {}, manifest, [], [], [],
                  report=lambda *args, **kwargs: updates.append((args, kwargs)))
    row = manifest[0]
    assert row["inference_level"] == "point_estimate"
    assert row["bootstrap_success"] < 80
    assert json.loads(row["bootstrap_failure_counts"])["missing_land_cover"] > 0
    assert json.loads(row["land_cover_block_counts"])["forest"] == 1
    assert row["bootstrap_category_support_ceiling"] == pytest.approx(1-(23/24)**24)
    assert "成功率不足" in row["inference_warning"]
    assert updates[-1][1]["done"] == 100
