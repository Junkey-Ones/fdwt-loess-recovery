"""Q1删失分类和伴随诊断的手算验收。"""
from copy import deepcopy
import pyarrow as pa
from workflow.run_module import load_config, DEFAULT_CONFIG
from src.M7.scr_q1_diagnostics import followup_subset, censor_audit, annual_companions


def test_complete_followup_keeps_early_recovery_and_drops_missing():
    """完整指结局可判定，不把提前恢复排除。"""
    rows=[dict(episode_id=k,followup_pentad=1,at_risk=True,recovery_event=k=="r",
               censor_administrative=k=="a",censor_reason=reason)
          for k,reason in [("r",None),("a","administrative"),("m","missing"),("d","data_end")]]
    selected=followup_subset(rows,"complete_followup")
    assert {r["episode_id"] for r in selected}=={"r","a"}
    events=[dict(episode_id=k,year=2010) for k in "ramd"]
    result=censor_audit(rows,events,"main",12,load_config(DEFAULT_CONFIG))[0]
    assert result["n_enrolled"]==4
    assert sum(result[f"n_{k}"] for k in ("recovered","administrative","missing","data_end"))==4
    assert result["ipcw_status"]=="insufficient_censoring_support"


def test_active_window_does_not_reenter_or_count_exit_recovery():
    """离窗当候恢复不能进入截断版；不得改写原始风险表。"""
    rows=[dict(episode_id="e",followup_pentad=t,t0_tmin=20,t_abs=20+t,at_risk=True,
               active_flag=active,recovery_event=t==2,censor_administrative=False,censor_reason=None)
          for t,active in [(1,True),(2,False),(3,True)]]
    before=deepcopy(rows)
    selected=followup_subset(rows,"active_window")
    assert len(selected)==1 and selected[0]["censor_reason"]=="season_end"
    assert rows==before and not selected[0]["recovery_event"]
    rows[0]["active_flag"]=None
    selected=followup_subset(rows,"active_window")
    assert selected[0]["followup_pentad"]==0 and not selected[0]["at_risk"]
    assert selected[0]["censor_reason"]=="phenology_missing"


def test_annual_companion_denominators():
    """固定植被域、有效窗回退分母和活跃候完整性分别核算。"""
    p=load_config(DEFAULT_CONFIG)
    rows=[dict(grid_id=g,year=2003,active_window_length_L=length,phenology_fallback=fb,
               active_flag=active,smp=smp,p_mm=rain)
          for g,length,fb,active,smp,rain in [("a",2,False,True,10.,1.),("a",2,False,True,None,2.),
                                            ("b",1,True,True,20.,None),("x",1,False,True,10.,1.)]]
    masks=[dict(grid_id=g,mask_include=g!="x") for g in ("a","b","x")]
    events=[dict(year=2003,route1_A_eligible=True)]
    row=annual_companions([pa.RecordBatch.from_pylist(rows)],masks,events,p)[0]
    assert row["n_grid_year"]==2 and row["mean_active_pentads"]==1.5
    assert row["phenology_fallback_rate"]==.5 and row["n_active_pentads"]==3
    assert row["smp_completeness"]==2/3 and row["precip_completeness"]==2/3
