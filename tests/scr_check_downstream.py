"""合成序列验证 M3–M10 的关键计算边界。
作者：Codex。版本：v0.1.0。输入：冻结配置及合成序列。
输出：pytest 验证结果。运行：python -m pytest tests/scr_check_downstream.py。
"""
import pytest

from src.M3.scr_build_climatology import gringorten
from src.M4.scr_detect_events import detect_events
from src.M5.scr_derive_outcomes import derive_outcomes
from src.M6.scr_link_exposures import link_exposures
from src.M7.scr_route1_summary import holm, recovery_risk, summarize
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
