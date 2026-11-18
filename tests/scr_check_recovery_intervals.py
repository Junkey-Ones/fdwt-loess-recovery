"""验证Q1整块自举、无支撑尾候和失败降级，不测试显著性。"""
from copy import deepcopy
import numpy as np
import pytest
from workflow.run_module import load_config, DEFAULT_CONFIG
from src.M7.scr_fit_recovery_risk import recovery_time_baseline


def fixture_data():
    """构造30块的完整恢复/行政删失历史。"""
    params = deepcopy(load_config(DEFAULT_CONFIG))
    params["block"]["bootstrap_n"] = 30
    events, risk, blocks = [], [], {}
    rng = np.random.default_rng(134)
    for b in range(30):
        grid = f"g{b}"
        blocks[grid] = str(b)
        for i in range(30):
            eid = f"{b}:{i}"
            events.append(dict(episode_id=eid, grid_id=grid))
            t = int(rng.geometric(.12+.005*b))
            for step in range(1, min(t, 6)+1):
                risk.append(dict(episode_id=eid, at_risk=True, followup_pentad=step, recovery_event=step == t))
    return params, events, risk, blocks


def test_curve_intervals_reproducible_and_point_estimate_unchanged():
    """固定种子可复现；新增区间不改变点估计且保持概率边界。"""
    p, events, risk, blocks = fixture_data()
    args = (risk, events, blocks, 6, 3, p["infer"])
    old, _ = recovery_time_baseline(*args)
    rows, support = recovery_time_baseline(*args, params=p)
    again, _ = recovery_time_baseline(*args, params=p)
    assert rows == again and support["bootstrap_success"] == 30
    assert support["n_resampling_block"] == 30 and support["n_eff"] == 30
    for a, b in zip(old, rows):
        assert a["hazard"] == b["hazard"] and a["cumulative_recovery"] == b["cumulative_recovery"]
        assert b["interval_status"] == "available"
        for low, high in [("hazard_ci_low", "hazard_ci_high"), ("cumulative_ci_low", "cumulative_ci_high")]:
            assert 0 <= b[low] <= b[high] <= 1
    assert all(a["cumulative_ci_low"] <= b["cumulative_ci_low"] for a,b in zip(rows,rows[1:]))


def test_curve_no_extrapolation_or_silent_block_loss():
    """没有风险集的后六候不外推，缺空间块直接阻断。"""
    p, events, risk, blocks = fixture_data()
    rows, support = recovery_time_baseline(risk, events, blocks, 12, 3, p["infer"], params=p)
    assert all(r["hazard"] is None and r["cumulative_ci_low"] is None for r in rows[6:])
    assert support["interval_status"] == "partial_or_unavailable"
    blocks.pop("g0")
    with pytest.raises(ValueError, match="缺少空间块"):
        recovery_time_baseline(risk, events, blocks, 6, 3, p["infer"], params=p)


def test_curve_failed_bootstrap_keeps_points(monkeypatch):
    """自举拟合失败必须计数并留空区间，不得过滤失败后强行放行。"""
    from src.M7 import scr_fit_recovery_risk as model
    p, events, risk, blocks = fixture_data()
    original, calls = model.fit_grouped_cloglog, []
    def fit(*args):
        calls.append(1)
        return original(*args) if len(calls) == 1 else (None, "nonconverged")
    monkeypatch.setattr(model, "fit_grouped_cloglog", fit)
    rows, support = model.recovery_time_baseline(risk, events, blocks, 6, 3, p["infer"], params=p)
    assert support["bootstrap_success"] == 0 and support["bootstrap_failure_counts"] == {"nonconverged":30}
    assert all(r["hazard"] is not None and r["hazard_ci_low"] is None for r in rows)


def test_bootstrap_counts_equal_whole_history_resampling(monkeypatch):
    """逐条历史加块重复权重，应与拟合器实际收到的充分统计量一致。"""
    from src.M7 import scr_fit_recovery_risk as model
    p, events, risk, blocks = fixture_data()
    original, calls = model.fit_grouped_cloglog, []
    def fit(design, n, d):
        calls.append((n.copy(),d.copy()))
        return original(design,n,d)
    monkeypatch.setattr(model,"fit_grouped_cloglog",fit)
    model.recovery_time_baseline(risk,events,blocks,6,3,p["infer"],params=p)
    keys=sorted(set(blocks.values()))
    sampled=np.random.default_rng(p["random"]["seed"]).integers(len(keys),size=len(keys))
    multiplicity=dict(zip(keys,np.bincount(sampled,minlength=len(keys))))
    labels={e["episode_id"]:blocks[e["grid_id"]] for e in events}
    n,d=np.zeros(6),np.zeros(6)
    for row in risk:
        weight=multiplicity[labels[row["episode_id"]]]
        n[row["followup_pentad"]-1]+=weight
        d[row["followup_pentad"]-1]+=weight*row["recovery_event"]
    assert np.array_equal(calls[1][0],n) and np.array_equal(calls[1][1],d)
