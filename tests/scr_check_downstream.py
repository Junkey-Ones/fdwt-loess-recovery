"""合成序列验证 M3–M10 的关键计算边界。
作者：Codex。版本：v0.1.0。输入：冻结配置及合成序列。
输出：pytest 验证结果。运行：python -m pytest tests/scr_check_downstream.py。
"""
import pytest

from src.M3.scr_build_climatology import gringorten
from src.M4.scr_detect_events import detect_events
from src.M5.scr_derive_outcomes import derive_outcomes
from src.M6.scr_link_exposures import link_exposures
from src.M7.scr_route1_summary import holm, recovery_risk, summarize, summarize_lags, trend_estimates
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
                       vegetation_annual_mean=100 if y == 2008 else y-2003, annual_valid=True)
                  for y in range(2003, 2009)]
    vegetation.append(dict(vegetation[0], phenology_mode="fixed_season", vegetation_annual_mean=999))
    result, clusters = link_exposures(master, rows, vegetation, {}, params)
    assert result[0]["LAI_base"] == 2 and result[0]["LAI_trend"] == 1
    assert result[0]["deep_SM_pre4"] is None
    assert clusters[0]["n_event"] == 1


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
    assert gap["p_mk"] is not None and gap["primary_p"] is None
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
