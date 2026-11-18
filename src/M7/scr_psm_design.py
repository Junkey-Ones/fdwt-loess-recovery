"""PSM设计阶段：冻结协变量、1:1匹配和匹配后平衡审计。
作者：Codex。不读取结局数值，不据效应选择匹配；效应推断另行验收。
输入已选定分析队列及params；输出配对、平衡和设计状态。
"""
import numpy as np
from src.M7.scr_fit_route1_models import design_matrix,fit_binomial_logit


def match_design(rows,params,*,_thresholds=None,_reference=None,_design=None):
    """高低四分位对照；固定种子顺序、无放回最近邻、logit原尺度caliper。"""
    terms=["LAI_base",*params["covariates"]["core"]]
    candidates=sorted([r for r in rows if r.get("LAI_trend") is not None and np.isfinite(r["LAI_trend"])
        and all(r.get(k) is not None and (bool(r[k]) if k=="land_cover" else np.isfinite(r[k])) for k in terms)],
        key=lambda r:r["episode_id"])
    audit=dict(n_input=len(rows),n_complete=len(candidates),status="insufficient_support")
    if len(candidates)<params["infer"]["min_n"]:return [],[],audit
    low,high=(_thresholds if _thresholds is not None else np.quantile([r["LAI_trend"] for r in candidates],
                         [params["psm"]["low_quantile"],params["psm"]["high_quantile"]]))
    audit.update(low_threshold=float(low),high_threshold=float(high))
    if low>=high:
        audit["status"]="overlapping_quantile_groups"
        return [],[],audit
    sample=[r for r in candidates if r["LAI_trend"]<=low or r["LAI_trend"]>=high]
    treated=np.array([r["LAI_trend"]>=high for r in sample],dtype=float)
    names,x,_=design_matrix(sample,["LAI_base"],params["covariates"]["core"])
    if _design is not None:
        names,original_x=_design
        x=np.array([original_x[r["episode_id"]] for r in sample])
    if x is None or np.linalg.matrix_rank(x)<x.shape[1]:
        audit["status"]="rank_deficient"
        return [],[],audit
    if min(treated.sum(),len(treated)-treated.sum())<params["infer"]["min_event_per_arm"]:
        return [],[],audit
    beta,status=fit_binomial_logit(x,treated,np.ones(len(sample)))
    if beta is None:
        audit["status"]=status
        return [],[],audit
    eta=x @ beta
    high_ids=np.flatnonzero(treated==1);low_ids=np.flatnonzero(treated==0)
    pooled_sd=np.sqrt((np.var(x[high_ids],axis=0,ddof=1)+np.var(x[low_ids],axis=0,ddof=1))/2)
    reference=(_reference if _reference is not None else {
        name:(float(x[high_ids,j].mean()-x[low_ids,j].mean()),float(pooled_sd[j]))
        for j,name in enumerate(names[1:],1)})
    lower=max(eta[high_ids].min(),eta[low_ids].min());upper=min(eta[high_ids].max(),eta[low_ids].max())
    rng=np.random.default_rng(params["random"]["seed"])
    controls=set(low_ids[(eta[low_ids]>=lower)&(eta[low_ids]<=upper)].tolist())
    eligible=high_ids[(eta[high_ids]>=lower)&(eta[high_ids]<=upper)]
    matches=[]
    for h in rng.permutation(eligible):
        if not controls:break
        c=min(controls,key=lambda j:(abs(eta[h]-eta[j]),sample[j]["episode_id"]))
        if abs(eta[h]-eta[c])<=params["psm"]["caliper"]:
            controls.remove(c);matches.append((int(h),c))
    audit.update(n_high=len(high_ids),n_low=len(low_ids),n_high_common_support=len(eligible),n_pair=len(matches),
                 n_high_unmatched=len(high_ids)-len(matches),status="no_matches")
    if not matches:return [],[],audit
    h,c=np.array(matches).T
    balance=[]
    for j,name in enumerate(names[1:],1):
        before,denominator=reference[name]
        after=float(x[h,j].mean()-x[c,j].mean())
        smd_before=before/denominator if denominator>0 else 0. if before==0 else None
        smd_after=after/denominator if denominator>0 else 0. if after==0 else None
        balance.append(dict(term=name,smd_before=smd_before,smd_after=smd_after,
                            passed=bool(smd_after is not None and abs(smd_after)<params["psm"]["max_abs_smd"])))
    audit["status"]="balanced_design_requires_effect_inference" if all(r["passed"] for r in balance) else "balance_failed_descriptive_only"
    # 只允许一次预设共同支撑内重拟合；不根据结局或效应反复搜索。
    if audit["status"]=="balance_failed_descriptive_only" and _thresholds is None and params["psm"]["common_support_refit_max"]:
        common=[r for i,r in enumerate(sample) if lower<=eta[i]<=upper]
        pairs,second_balance,second_audit=match_design(common,params,_thresholds=(low,high),_reference=reference,
            _design=(names,{r["episode_id"]:x[i] for i,r in enumerate(sample)}))
        second_audit.update(initial_design=audit,common_support_refit=True)
        return pairs,second_balance,second_audit
    pairs=[dict(pair_id=i,high_episode_id=sample[h]["episode_id"],low_episode_id=sample[c]["episode_id"],
                logit_distance=float(abs(eta[h]-eta[c]))) for i,(h,c) in enumerate(matches)]
    return pairs,balance,audit
