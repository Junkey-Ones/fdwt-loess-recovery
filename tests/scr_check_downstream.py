"""合成序列验证 M3–M10 的关键计算边界。
作者：Codex。版本：v0.1.0。输入：冻结配置及合成序列。
输出：pytest 验证结果。运行：python -m pytest tests/scr_check_downstream.py。
"""
from datetime import date, timedelta

import pyarrow as pa
import pytest

from src.M3.scr_build_climatology import gringorten
from src.M4.scr_detect_events import detect_events
from src.M5.scr_derive_outcomes import derive_outcomes
from src.M6.scr_background_climate import background_climate
from src.M6.scr_link_exposures import link_exposures
from src.M7.scr_route1_summary import (
    audit_model_samples, holm, recovery_risk, restore_fr_eligibility, summarize, summarize_lags, trend_estimates,
)
from src.M7.scr_fit_recovery_risk import fit_grouped_cloglog, natural_spline, recovery_time_baseline
from src.M8.scr_describe_exits import cumulative_incidence, sample_audit
from src.M8.scr_fit_cause_specific import fit_cause_specific
from src.M8.scr_encode_exits import encode_exits
from src.M9.scr_match_events import match_grid_events
from src.M10.scr_review_results import review_events
from workflow.run_module import DEFAULT_CONFIG, load_config


@pytest.fixture
def params():
    """读取统一参数。"""
    return load_config(DEFAULT_CONFIG)


def synthetic_series():
    """构造并列最低、终止阈值等号及 R/Z 重叠。"""
    values = [50, 39, 19, 10, 10, 21, 45, 50, 50]
    return [dict(product_combo="era5land__era5land", grid_id="x", support_id="own_full", year=2008,
                 t_abs=t, pentad=t, smp=smp, active_flag=True, phenology_mode="dynamic", p_mm=9 if t==6 else 0,
                 p95_mm=8, p95_usable=True, w=1 if t==6 else -1, sm_deep_mm=100)
            for t, smp in enumerate(values, 1)]


def test_event_outcomes_and_review(params):
    """检查最小值取首次、完整窗口、双分支及独立复算。"""
    rows = synthetic_series()
    events, _ = detect_events(rows, params)
    assert len(events) == 1
    assert [events[0][key] for key in ("t_s", "t_min", "t_e")] == [2, 4, 6]
    master, rain, branches, _ = derive_outcomes(events, rows, params)
    event = master[0]
    assert (event["RT"], event["delta_SMP"], event["RR"]) == (2, 11, 5.5)
    assert event["F_R_subtype"] == "sync"
    assert len(rain) == 1
    assert {row["branch"] for row in branches} == {"F_R", "F_Z"}
    assert review_events(master, rows, params)[0]["passed"]
    lag_fr, offset, lag_p = summarize_lags([event, {**event, "route1_A_eligible": False}])
    assert (lag_fr["n_event"], lag_fr["median"], offset["median"], lag_p["n_event"]) == (1, 2, 0, 2)
    altered = {**event, "t_w_R": 7, "Lag_FR": 3, "Offset_FR": 1, "F_R_subtype": "post"}
    assert "F_R 判定或首个降水候" in review_events([altered], rows, params)[0]["issues"]
    incomplete = [row for row in rows if row["t_abs"] != 7]
    assert "F_R 判定或首个降水候" in review_events(master, incomplete, params)[0]["issues"]
    assert [row["recovery_event"] for row in recovery_risk(master, rows, params)] == [False, True]


def test_fr_after_active_window(params):
    """首个接续候出窗时保留原始阳性，并从路线一 Q2 样本排除。"""
    rows = synthetic_series()
    rows[5].update(p_mm=0, w=-1)
    rows[6].update(p_mm=9, w=1, active_flag=False)
    events, _ = detect_events(rows, params)
    master, _, branches, _ = derive_outcomes(events, rows, params)
    event = master[0]
    assert event["route1_A_eligible"] and event["F_R"] and event["t_w_R"] == 7
    assert not event["route1_FR_eligible"]
    assert any(row["branch"] == "F_R" for row in branches)
    q1, q2 = summarize(master, params)
    assert next(row for row in q1 if row["year"] == 2008)["n_event"] == 1
    year = next(row for row in q2 if row["year"] == 2008)
    assert (year["n_known"], year["n_positive"], year["n_unknown"], year["n_outside_active_window"]) == (0, 0, 0, 1)
    assert summarize_lags(master)[0]["n_event"] == 0
    event.pop("route1_FR_eligible")
    restore_fr_eligibility(master, rows)
    assert not event["route1_FR_eligible"]


def test_short_censored_events_do_not_bypass_duration(params):
    """末端删失仍须达到观察持续门槛；达到门槛的右删失必须保留。"""
    rows = synthetic_series()[:5]
    events, audit = detect_events(rows, params)
    assert not events and audit[0]["exclusion_reason"] == "持续不足"
    rows.append(dict(rows[-1], t_abs=6, pentad=6, smp=15))
    events, _ = detect_events(rows, params)
    assert len(events) == 1 and events[0]["right_censored"]
    assert events[0]["observed_duration"] == 4


def test_duplicate_pentads_fail_instead_of_overwrite(params):
    """重复候不允许被字典静默覆盖。"""
    from src.M5.scr_derive_outcomes import index_series
    rows = synthetic_series()
    rows.append(dict(rows[-1], smp=0))
    with pytest.raises(ValueError, match="主键重复"):
        detect_events(rows, params)
    with pytest.raises(ValueError, match="主键重复"):
        index_series(rows)


def test_q3_audit_counts_complete_cases_and_shared_exposures():
    """核对已知降水、post 对照排除、右删失和共享暴露簇。"""
    events = [dict(episode_id=key, route1_FR_eligible=True, F_R=flag, F_R_subtype=subtype)
              for key, flag, subtype in (("a", True, "pre"), ("b", False, None), ("c", True, "post"),
                                         ("d", None, None))]
    exposure = [dict(episode_id=key, exposure_complete_L=True, exposure_complete_D=key != "b",
                     exposure_complete_I=key != "b", LAI_exposure_cluster="x:2008")
                for key in "abcd"]
    risk = [dict(episode_id=key, at_risk=key != "d", recovery_event=key == "a") for key in "abcd"]
    audit = audit_model_samples(events, exposure, risk)
    assert audit["q2_pre_sync"]["n_event"] == 2
    assert audit["q3_recovery_L"]["n_event"] == 3 and audit["q3_recovery_L"]["n_outcome"] == 1
    assert audit["q3_recovery_L"]["n_exposure"] == 1
    assert audit["q3_fr_I"]["n_event"] == 2


def test_m7_reads_nonempty_grid_handoffs(tmp_path, params):
    """通过实际 Parquet 接口核对按格点读取、旧交接和候选样本回执。"""
    import pyarrow.parquet as pq
    from workflow.run_downstream import compute_module

    rows = synthetic_series()
    events, _ = detect_events(rows, params)
    master, _, _, _ = derive_outcomes(events, rows, params)
    master[0].pop("route1_FR_eligible")
    tables = {}
    for name, records in {
        "grid_pentad": list(reversed(rows)),
        "event_master": master,
        "grid_manifest": [dict(grid_id="x", block_id="b")],
        "superblock_membership": [dict(block_id="b", superblock_id="b")],
        "event_exposure": [dict(episode_id=master[0]["episode_id"], exposure_complete_L=False,
                                exposure_complete_D=False, exposure_complete_I=False)],
    }.items():
        tables[name] = tmp_path / f"{name}.parquet"
        pq.write_table(pa.Table.from_pylist(records), tables[name])
    outputs, status, details = compute_module("M7", tables, {}, params, {}, {})
    assert status == "descriptive_only"
    assert any(row["recovery_event"] for row in outputs["route1_recovery_person_pentad"])
    assert details["model_candidate_samples"]["q2_fr"]["n_event"] == 1


def test_route1_q2_q3_models(params):
    """有支撑时拟合全部主模型，并复核边际预测和校正家族。"""
    import numpy as np
    from src.M7.scr_fit_route1_models import fit_route1_models, logistic

    rng = np.random.default_rng(178)
    params["covariates"]["core"] = ["elevation_m"]
    params["block"]["bootstrap_n"] = 8
    params["infer"]["epv_min"] = 3
    events, exposure, risk = [], [], []
    for i in range(420):
        episode, grid = str(i), str(i % 30)
        lai, base, deep, elevation = rng.normal(size=4)
        year = 2008+i % 13
        fr = rng.random() < logistic(0.5*lai+0.4*lai*deep)
        subtype = "post" if fr and i % 7 == 0 else "pre" if fr else None
        events.append(dict(episode_id=episode, F_R=bool(fr), F_R_subtype=subtype,
                           route1_FR_eligible=True, RR=2*fr+rng.normal(),
                           delta_SMP=3*fr+rng.normal(), product="era5land", definition_id="main",
                           support_id="own_full"))
        exposure.append(dict(episode_id=episode, grid_id=grid, year=year, LAI_trend=lai,
                             LAI_base=base, LAI_exposure_cluster=f"{grid}:{year}", elevation_m=elevation,
                             deep_SM_pre4_percentile=50+10*deep, exposure_complete_L=True,
                             exposure_complete_D=True, exposure_complete_I=True))
        for step in range(1, 13):
            recovered = rng.random() < -np.expm1(-np.exp(-2.5+0.3*lai+0.4*lai*deep))
            risk.append(dict(episode_id=episode, followup_pentad=step, at_risk=True, recovery_event=recovered))
            if recovered:
                break
    blocks = {str(i): f"b{i}" for i in range(30)}
    result = fit_route1_models(events, exposure, risk, blocks, {}, params, {})
    assert len(result["model_fit_manifest"]) == 9
    assert all(row["convergence_status"] in ("fitted", "point_estimate") for row in result["model_fit_manifest"])
    tests = [row for row in result["model_result"] if row.get("test_id")]
    assert len(tests) == 6
    assert all(row["p_holm"] >= row["p_raw"] for row in tests)
    assert next(row for row in tests if row["test_id"] == "fr_pre_sync_rr_contrast")["estimate"] == pytest.approx(2, abs=.35)
    assert len(result["model_marginal"]) == 12
    assert all(0 <= row["predicted_probability"] <= 1 for row in result["model_marginal"])


def test_missing_hplus_one_and_leakage(params):
    """H+1 窗口缺失不归 A，事件年植被值不进入历史暴露。"""
    rows = synthetic_series()[:6]
    params["route2"]["h"] = 4
    events, _ = detect_events(rows, params)
    master, _, _, _ = derive_outcomes(events, rows, params)
    assert master[0]["F_R"] is None and master[0]["RT"] == 2
    _, exits, _ = encode_exits(master, rows, params)
    assert exits[0]["exit_type"] is None and exits[0]["exit_type_unknown"]
    vegetation = [dict(grid_id="x", year=y, vegetation_product="mcd15a3h", phenology_mode="dynamic",
                       vegetation_annual_mean=100 if y == 2008 else y-2003, annual_valid=True,
                       temporal_coverage=0.7, spatial_coverage=0.7, mask_version="main", qc_version=params["lai"]["qc_version"])
                  for y in range(2003, 2009)]
    vegetation.append(dict(vegetation[0], phenology_mode="fixed_season", vegetation_annual_mean=999))
    vegetation.append(dict(vegetation[0], qc_version="strict", vegetation_annual_mean=999))
    result, clusters = link_exposures(master, rows, vegetation, {}, params)
    assert result[0]["LAI_base"] == 2 and result[0]["LAI_trend"] == 1
    assert result[0]["deep_SM_pre4"] is None
    assert clusters[0]["n_event"] == 1
    vegetation[0]["temporal_coverage"] = 0.69
    rejected, _ = link_exposures(master, rows, vegetation, {}, params)
    assert not rejected[0]["LAI_full_window"]
    vegetation[0]["temporal_coverage"] = 0.7
    covariates = dict.fromkeys(params["covariates"]["core"], 1.0)
    covariates["sand_0_30"] = float("nan")
    master[0].update(land_cover="forest", active_window=30)
    incomplete, _ = link_exposures(master, rows, vegetation, {"x": covariates}, params)
    assert incomplete[0]["LAI_full_window"] and not incomplete[0]["exposure_complete_L"]
    assert incomplete[0]["core_covariate_missing_reason"] == "sand_0_30"
    for row in vegetation:
        row["qc_version"] = "outdated"
    with pytest.raises(ValueError, match="QC版本"):
        link_exposures(master, rows, vegetation, {}, params)


def test_lai_four_of_five_uses_actual_years_and_preserves_gates(params):
    """缺中间一年仍按真实时间求斜率；五年全有效则全部使用。"""
    import json

    rows = synthetic_series()
    events, _ = detect_events(rows, params)
    master, _, _, _ = derive_outcomes(events, rows, params)
    master[0].update(land_cover="forest", active_window=30)
    covariates = {"x": dict.fromkeys(params["covariates"]["core"], 1.0)}
    vegetation = [dict(grid_id="x", year=y, vegetation_product="mcd15a3h", phenology_mode="dynamic",
                       vegetation_annual_mean=100 if y == 2008 else y-2003, annual_valid=True,
                       temporal_coverage=0.7, spatial_coverage=0.7,
                       mask_version=params["lai"]["mask_version"], qc_version=params["lai"]["qc_version"])
                  for y in (2003, 2004, 2006, 2007, 2008)]
    strict, _ = link_exposures(master, rows, vegetation, covariates, params)
    relaxed, audit = link_exposures(master, rows, vegetation, covariates, params, variant="lai_four_of_five")
    assert strict[0]["LAI_base"] is None and not strict[0]["exposure_complete_L"]
    result = relaxed[0]
    assert result["LAI_base"] == 2 and result["LAI_trend"] == 1
    assert result["LAI_window_eligible"] and not result["LAI_full_window"]
    assert result["exposure_complete_L"] and not result["exposure_complete_I"]
    assert result["LAI_required_valid_years"] == 4
    assert json.loads(result["LAI_valid_years"]) == [2003, 2004, 2006, 2007]
    assert result["LAI_valid_year_span"] == 4
    assert result["LAI_exposure_cluster"] == "x:2008"
    assert audit[0]["analysis_id"] == result["exposure_version"] == "lai_four_of_five"
    vegetation[0]["temporal_coverage"] = 0.69
    rejected, audit = link_exposures(master, rows, vegetation, covariates, params, variant="lai_four_of_five")
    assert rejected[0]["LAI_n_valid_years"] == 3 and not rejected[0]["LAI_window_eligible"] and not audit
    vegetation[0]["temporal_coverage"] = 0.7
    vegetation.append(dict(vegetation[0], year=2005, vegetation_annual_mean=7))
    complete, _ = link_exposures(master, rows, vegetation, covariates, params, variant="lai_four_of_five")
    assert complete[0]["LAI_n_valid_years"] == 5 and complete[0]["LAI_full_window"]
    assert complete[0]["LAI_base"] == 3


def test_registered_lai_menu_options():
    """向导公开严格与宽松方案，并保留固定季节选项。"""
    from workflow.run_module import ROOT, variant_options

    options = {key: label for key, label, _ in variant_options(load_config(ROOT / "config/specification_matrix.yaml"))}
    assert "5/5" in options["main"] and "4/5" in options["lai_four_of_five"]
    assert "fixed_season" in options


def test_background_climate_rejects_duplicate_dates_and_nonfinite_days(params):
    """检查跨批日期重复及 NaN 导致的变量缺失。"""
    params["covariates"]["climate_years"] = [2003, 2003]
    dates = [date(2003, 1, 1) + timedelta(days=i) for i in range(365)]
    batch = pa.record_batch(dict(date=dates, grid_id=["x"] * 365,
                                 p_mm=[float("nan")] + [1.0] * 364, t2m_c=[20.0] * 365))
    result = background_climate([batch], params)["x"]
    assert result["annual_p_mean_mm"] is None and result["apr_sep_t2m_mean_c"] == 20.0
    with pytest.raises(ValueError, match="重复格点日期"):
        background_climate([batch.slice(0, 364), batch.slice(363, 1)], params)


def test_gap_does_not_reconnect(params):
    """缺口前发生的事件不越过缺口恢复。"""
    rows = synthetic_series()
    rows[5]["smp"] = None
    events, _ = detect_events(rows, params)
    assert not events
    rows[5]["smp"] = 20
    rows[6]["smp"] = None
    events, _ = detect_events(rows, params)
    assert events[0]["right_censored"] and events[0]["censor_type"] == "missing"
    master, _, _, _ = derive_outcomes(events, rows, params)
    risk = recovery_risk(master, rows, params)
    assert risk[-1]["censor_missing"] and not any(row["recovery_event"] for row in risk)


def test_rank_holm_and_matching(params):
    """平均秩、缺失检验占位和匹配冲突均可复核。"""
    values = list(range(20)) * 2
    assert gringorten(sorted(values), 0, params["clim"]) == pytest.approx((1.5-.44)/(40+.12))
    assert holm([.01, None, .03]) == [.03, None, .06]
    reference = [dict(grid_id="x", episode_id=name, t_s=t, t_min=t+1)
                 for name, t in [("a", 1), ("b", 3)]]
    alternative = [dict(grid_id="x", episode_id="c", t_s=2, t_min=3)]
    assert len(match_grid_events(reference, alternative, 1)) == 1


def test_event_period_and_empty_summary(params):
    """背景输入中的事件不得扩张研究时期，零事件年份保留分母。"""
    rows = synthetic_series()
    for row in rows:
        row["year"] = 2002
    assert detect_events(rows, params) == ([], [])
    q1, q2 = summarize([], params)
    assert [row["year"] for row in q1] == list(range(2003, 2024))
    assert all(row["n_event"] == 0 and row["RR"] is None for row in q1)
    assert all(row["n_known"] == 0 and row["proportion"] is None for row in q2)


def test_q1_trend_threshold_and_holm(params):
    """检查连续年序列的自相关触发、并列零方差和有效年门槛。"""
    annual = [dict(year=year, RT=2 * (year - 2003), delta_SMP=5.0, RR=None)
              for year in range(2003, 2024)]
    rt, delta, rr = trend_estimates(reversed(annual), params)
    assert rt["status"] == "passed"
    assert rt["sen_slope"] == 2
    assert rt["primary_test"] == "hamed_rao"
    assert rt["variance_factor"] == 1
    assert rt["p_mk"] == pytest.approx(rt["p_hamed_rao"])
    assert rt["primary_p_holm"] == pytest.approx(3 * rt["primary_p"])
    assert delta["primary_test"] == "mann_kendall"
    assert delta["sen_slope"] == 0 and delta["primary_p_holm"] == 1
    assert rr["status"] == "insufficient_years" and rr["primary_p_holm"] is None
    gap = trend_estimates(annual[:9] + annual[10:], params)[0]
    assert gap["status"] == "annual_gaps" and gap["sen_slope"] == 2
    assert gap["primary_test"] == "mann_kendall" and gap["primary_p"] == gap["p_mk"]
    assert gap["primary_p_holm"] == pytest.approx(3 * gap["p_mk"])
    assert gap["ljung_box_lag1_p"] is None and gap["p_hamed_rao"] is None
    step = [{**row, "RT": row["RT"] + (row["year"] >= 2018)} for row in annual]
    rt = trend_estimates(step, params)[0]
    assert rt["sen_slope"] == 2
    assert rt["variance_factor"] == pytest.approx(89731 / 23275)
    assert rt["p_hamed_rao"] > rt["p_mk"]
    short = annual[:17]
    assert trend_estimates(short, params, minimum_years=15)[0]["status"] == "passed"
    assert trend_estimates(short, params, minimum_years=20)[0]["status"] == "insufficient_years"


def test_review_flags_inconsistent_censoring(params):
    """识别误标为条件 A 的右删失事件。"""
    rows = synthetic_series()
    rows[5]["smp"] = 20
    rows[6]["smp"] = None
    events, _ = detect_events(rows, params)
    master, _, _, _ = derive_outcomes(events, rows, params)
    master[0]["route1_A_eligible"] = True
    reviewed = review_events(master, rows, params)
    assert not reviewed[0]["passed"]


def test_recovery_cloglog_time_baseline(params):
    """用已知风险拟合分组二项模型并检查无支撑时的输出。"""
    import numpy as np

    design = natural_spline(range(1, 13), 12)
    sizes = np.full(12, 100.0)
    fit, status = fit_grouped_cloglog(design, sizes, sizes * 0.2)
    assert fit_grouped_cloglog(design, sizes, sizes * 0) == (None, "no_outcome_variation")
    assert fit_grouped_cloglog(design, sizes, sizes) == (None, "no_outcome_variation")
    assert status == "point_estimate"
    assert -np.expm1(-np.exp(design @ fit)) == pytest.approx([0.2] * 12)
    fit, status = fit_grouped_cloglog(design, sizes, np.arange(10, 34, 2))
    assert status == "point_estimate"
    hazards = -np.expm1(-np.exp(design @ fit))
    assert 0 < hazards[0] < hazards[-1] < 1
    output, support = recovery_time_baseline([], [], {}, 12, 3, params["infer"])
    assert support["status"] == "insufficient_support"
    assert len(output) == 12 and all(row["hazard"] is None for row in output)


def test_route2_cif_preserves_competing_risk_and_strict_reclassification(params):
    """用已知风险集手算累计发生率，检验 post 重分型及删失。"""
    a = dict(followup_pentad=1, at_risk=True, censored=False, exit_A=True, exit_B=False)
    b = dict(followup_pentad=2, at_risk=True, censored=False, exit_A=False, exit_B=True, F_R_subtype="post")
    person = [a, {**a, "exit_A": False}, {**a, "exit_A": False},
              b, {**b, "at_risk": False, "censored": True, "exit_B": False}]
    final = cumulative_incidence(person, 2)[-1]
    assert (final["cif_a"], final["cif_b"], final["probability_c"]) == pytest.approx((1/3, 2/3, 0))
    strict = cumulative_incidence(person, 2, strict=True)[-1]
    assert (strict["cif_a"], strict["cif_b"], strict["n_censored"]) == (1, 0, 1)
    events = [dict(episode_id="e", grid_id="g")]
    exits = [dict(episode_id="e", exit_type="B", censor_reason=None)]
    rows, gate = sample_audit(events, exits, {"g": "b"}, params["route2"])
    assert rows[1]["n_event"] == 1
    assert gate["max_b_share_per_block"] == 1 and not gate["b_share_gate_met"]
    assert not gate["multivariable_count_gate_met"]


def test_route2_logistic_time_baseline():
    """以固定风险的充分统计量验证两套 logistic 拟合和概率递推。"""
    curve = [dict(followup_pentad=t, n_at_risk=100, n_exit_a=10, n_exit_b=20) for t in range(1, 7)]
    rows, details = fit_cause_specific(curve, 6, 3, 10)
    assert details["status"] == "point_estimate"
    assert rows[0]["hazard_a"] == pytest.approx(0.1)
    assert rows[0]["hazard_b"] == pytest.approx(0.2)
    assert rows[-1]["probability_c"] == pytest.approx(0.7 ** 6)
    assert sum(rows[-1][key] for key in ("cif_a", "cif_b", "probability_c")) == pytest.approx(1)
    assert fit_cause_specific(curve, 6, 3, 20)[1]["status"] == "model_unavailable"


def test_m6_native_lai_leap_year_overlap_and_missing_pixels():
    """闰年末候覆盖六天，缺测像元只减少对应像元的天数。"""
    import numpy as np
    from src.M2.scr_prepare_era5land import pentad_calendar
    from src.M6.scr_prepare_vegetation import composite_weights, native_year

    weights = composite_weights(2020, pentad_calendar(2020, 2020, 73, 2000))
    assert weights[-1] == [(90, 4), (91, 2)]
    stack = np.full((92, 3), 255, dtype=np.uint8)
    stack[90] = [10, 255, 255]
    stack[91] = [40, 20, 255]
    values, days, counts, observed = native_year(stack, weights, [0, 72])
    np.testing.assert_array_equal(values, [20, 20, 0])
    np.testing.assert_array_equal(days, [6, 2, 0])
    np.testing.assert_array_equal(counts, [1, 1, 0])
    assert observed == [72]
