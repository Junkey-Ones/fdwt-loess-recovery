"""匹配设计不读取结局，输入排列不改变固定种子配对。"""
from copy import deepcopy
import numpy as np
from src.M7.scr_psm_design import match_design
from workflow.run_module import DEFAULT_CONFIG,load_config


def test_design_is_deterministic_and_outcome_blind():
    p=load_config(DEFAULT_CONFIG);p["covariates"]["core"]=["elevation_m"]
    rng=np.random.default_rng(8)
    rows=[dict(episode_id=str(i),LAI_trend=float(rng.normal()),LAI_base=float(rng.normal()),
               elevation_m=float(rng.normal()),F_R=bool(i%2)) for i in range(800)]
    original=deepcopy(rows)
    first=match_design(rows,p)
    changed=[dict(r,F_R=not r["F_R"]) for r in rows[::-1]]
    assert first==match_design(changed,p) and rows==original
    pairs,_,audit=first
    assert pairs and len({r["low_episode_id"] for r in pairs})==len(pairs)
    assert len({r["high_episode_id"] for r in pairs})==len(pairs)
    assert all(r["logit_distance"]<=p["psm"]["caliper"] for r in pairs)


def test_contrasts_missing_pairs_and_year_gate():
    from src.M7.scr_psm_contrasts import matched_contrasts
    p=load_config(DEFAULT_CONFIG)
    rows=[];pairs=[]
    for i in range(300):
        for arm in (0,1):
            rows.append(dict(episode_id=f"{i}_{arm}",grid_id=str(i%30),year=2000+i//30,
                             F_R=None if i==0 and arm==0 else bool(arm),
                             RR=float(i%7+arm),delta_SMP=float(i%11+arm)))
        pairs.append(dict(high_episode_id=f"{i}_1",low_episode_id=f"{i}_0"))
    blocks={str(i):str(i) for i in range(30)}
    audit=dict(status="balanced_design_requires_effect_inference")
    result=matched_contrasts(pairs,rows,blocks,audit,p)
    fr=next(r for r in result if r["outcome"]=="F_R")
    assert fr["n_pair"]==299 and fr["n_pair_missing"]==1 and fr["estimate"]==1
    assert fr["ci_low"] is None  # 常量结局没有可估方差，不能制造零宽区间。
    assert all(r["estimate"]==1 for r in result)
    assert matched_contrasts(pairs,rows,blocks,dict(status="balance_failed_descriptive_only"),p)==[]
    for row in rows:row["year"]=2000
    assert all(r["ci_low"] is None for r in matched_contrasts(pairs,rows,blocks,audit,p))


def test_psm_pipeline_scope_and_registered_columns():
    import pytest
    from src.M7.scr_psm_contrasts import psm_analysis
    p=load_config(DEFAULT_CONFIG)
    schema=load_config(DEFAULT_CONFIG.parent / "schema_registry.yaml")["tables"]
    output,audit=psm_analysis([],[],{},p)
    assert set(output)=={"psm_pairs","psm_balance","psm_contrast"}
    assert all(name in schema for name in output)
    assert audit["status"]=="insufficient_support"
    p["psm"]["output_scope"]="ATT_high"
    with pytest.raises(ValueError,match="未实现总体ATT"):
        psm_analysis([],[],{},p)
