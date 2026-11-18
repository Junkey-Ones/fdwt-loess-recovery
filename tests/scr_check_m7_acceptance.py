"""验证新增验收会发现轨迹错误、按真实年份定位缺年，并调用完整模拟接口。"""
import pytest
from src.M7.scr_accept_route1 import audit_curve, four_year_support
from notebooks.q1_full_coverage import simulate
from workflow.run_module import DEFAULT_CONFIG, load_config


def test_bad_curve_and_missing_year():
    row = dict(episode_id="a",followup_pentad=1,at_risk=True,recovery_event=True,censor_reason=None)
    curve = [dict(followup_pentad=1,n_at_risk=1,n_recovery=1,cumulative_recovery=1)]
    assert audit_curve([row],curve,{(1,"recovered"):1})[0]["censored"] == 0
    with pytest.raises(ValueError,match="独立复算"):
        audit_curve([row],curve,{(1,"missing"):1})
    exposure = dict(year=2010,window_start_year=2005,window_end_year=2009,LAI_n_valid_years=4,
                    LAI_valid_years="[2005,2006,2008,2009]",grid_id="g",land_cover="grassland")
    exposure.update(episode_id="a", LAI_in_exposure_period=False, LAI_window_eligible=False,
                    exposure_complete_L=False, exposure_complete_I=False)
    audit = four_year_support([exposure],{"g":"b"},[dict(episode_id="a")],[])[0]
    assert (audit["missing_position"],audit["n_raw"],audit["n_event"],audit["n_period"]) == (3,1,0,0)


def test_full_coverage_smoke():
    params = load_config(DEFAULT_CONFIG)
    params["infer"]["year_score_calibration"].update(spatial_clusters=22,year_clusters=12,observations_per_cell=1)
    params["block"]["bootstrap_n"] = 3
    rows = list(simulate(params,1))
    assert len(rows) == 3*12*4
    assert all(r["valid"]+r["unavailable"] == 1 for r in rows)
    assert any(r["valid"] for r in rows)



def test_compare_checks_shared_exposure_and_d_model(tmp_path, monkeypatch):
    """相同表通过，D模型悄然变化即阻止通过。"""
    import json
    from notebooks import m7_compare_schemes as comparison
    strict, relaxed = "2026-11-18_严格", "2026-11-18_修订"
    monkeypatch.setattr(comparison, "ROOT", tmp_path)
    for alias, variant in ((strict,"main"),(relaxed,"lai_four_of_five")):
        target = tmp_path/"outputs"/alias
        target.mkdir(parents=True)
        (target/"protocol_freeze.json").write_text(json.dumps({"variant":variant}),encoding="utf8")
    changed = False
    def table(alias,module,name):
        if module == "M6":
            return [dict(episode_id="e",exposure_complete_I=True,LAI_base=1,LAI_trend=2,deep_SM_pre4_percentile=3)]
        if name == "model_result":
            return [dict(analysis_id="q3_fr_D",estimate=int(alias == relaxed and changed))]
        return []
    monkeypatch.setattr(comparison,"table",table)
    comparison.compare(strict,relaxed)
    changed = True
    with pytest.raises(ValueError,match="model_result"):
        comparison.compare(strict,relaxed)


def test_nonforest_keeps_q3_d_eligibility(monkeypatch):
    """非森林对照按地类筛事件，D模型可保留缺LAI的草地事件。"""
    from src.M7 import scr_model_sensitivity as sensitivity
    params = load_config(DEFAULT_CONFIG)
    events = [dict(episode_id=k) for k in ("f","g","c")]
    exposures = [dict(episode_id=k,land_cover=c,exposure_complete_L=False)
                 for k,c in zip(("f","g","c"),("forest","grassland","cropland"))]
    def fit(events, *args, **kwargs):
        assert [r["episode_id"] for r in events] == ["g","c"]
        assert kwargs["selection"] == "q3" and kwargs["exploratory"]
        return {name:[] for name in sensitivity.TABLES}
    monkeypatch.setattr(sensitivity,"fit_route1_models",fit)
    sensitivity.fit_sensitivity("nonforest",events,exposures,[],{},{},params,{})
