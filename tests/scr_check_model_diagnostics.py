"""等价、无区间和缺少预设界的解释边界。"""
from workflow.run_module import DEFAULT_CONFIG, load_config
from src.M7.scr_model_diagnostics import model_diagnostics


def test_equivalence_and_missing_interval_are_distinct():
    p=load_config(DEFAULT_CONFIG)
    manifest=[dict(analysis_id="q3_fr_L",model_family="logit",n_eff=46)]
    coefficient=dict(analysis_id="q3_fr_L",term="LAI_trend",test_id="lai_trend_fr",test_family="q3",
                     estimate=0.,ci_low=-.1,ci_high=.1,scale="link",p_holm=1.)
    result=model_diagnostics(manifest,[coefficient],p)[0]
    assert result["equivalence_status"]=="within_equivalence_bounds"
    assert result["gam_status"]=="retain_linear_insufficient_support" and result["mde"]>0
    missing=model_diagnostics(manifest,[dict(coefficient,ci_low=None)],p)[0]
    assert missing["equivalence_status"]=="interval_unavailable" and missing["mde"] is None
    assert missing["interpretation"]=="insufficient_evidence"


def test_continuous_sd_and_no_or_bound_for_cloglog():
    p=load_config(DEFAULT_CONFIG)
    coefficient=dict(analysis_id="m",term="x",test_id="x",test_family="q2",estimate=0.,
                     ci_low=-.15,ci_high=.15,scale="original",p_holm=1.)
    result=model_diagnostics([dict(analysis_id="m",model_family="median",n_eff=60,outcome_sd=2.)],[coefficient],p)[0]
    assert result["equivalence_high"]==.2 and result["equivalence_status"]=="within_equivalence_bounds"
    result=model_diagnostics([dict(analysis_id="m",model_family="cloglog",n_eff=60)],[coefficient],p)[0]
    assert result["equivalence_status"]=="no_prespecified_bound"
