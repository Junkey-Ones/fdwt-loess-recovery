"""固定匹配设计下的高低组描述性对照；不声称总体因果ATT。
作者：Codex。空间、年份、配对三向得分协方差；匹配选择的不确定性不包含。
由统一M7调用，先通过平衡门槛，单列条件推断范围。
"""
from itertools import combinations
from statistics import NormalDist
import numpy as np
from src.M7.scr_cluster_scores import grouped_scores
from src.M7.scr_fit_route1_models import effective_count


def matched_contrasts(pairs,rows,blocks,design_audit,params):
    """整对保留；三向聚类交叉项按容斥求和，不传播合并空间块。"""
    if design_audit.get("status")!="balanced_design_requires_effect_inference":return []
    lookup={r["episode_id"]:r for r in rows};output=[]
    for outcome in ("F_R","RR","delta_SMP"):
        selected=[(lookup[p["high_episode_id"]],lookup[p["low_episode_id"]]) for p in pairs]
        selected=[(a,b) for a,b in selected if all(r.get(outcome) is not None and np.isfinite(r[outcome])
                  and blocks.get(r["grid_id"]) is not None for r in (a,b))]
        n=len(selected)
        if not n:continue
        high=np.array([r[0][outcome] for r in selected],dtype=float)
        low=np.array([r[1][outcome] for r in selected],dtype=float)
        flat=[r for pair in selected for r in pair]
        labels=[[blocks[r["grid_id"]] for r in flat],[r["year"] for r in flat],np.repeat(np.arange(n),2).tolist()]
        score=np.column_stack((high-high.mean(),-(low-low.mean()))).reshape(-1,1)/n
        variance=0.;valid=True
        for size in (1,2,3):
            for subset in combinations(range(3),size):
                groups=list(zip(*(labels[i] for i in subset)))
                sums=grouped_scores(score,groups);g=len(sums)
                if g<2:valid=False;continue
                variance+=(-1)**(size+1)*float(np.sum(sums**2))*g/(g-1)
        supported=(n>=params["infer"]["min_n"] and len(set(labels[1]))>=params["infer"]["year_score_bootstrap"]["min_clusters"]
                   and len(set(labels[0]))>=params["infer"]["min_blocks"]
                   and effective_count(labels[0])>=params["infer"]["min_n_eff"])
        estimate=float(high.mean()-low.mean());ci=(None,None)
        if supported and valid and variance>0:
            half=NormalDist().inv_cdf(1-params["multiple_testing"]["family_alpha"]/2)*np.sqrt(variance)
            ci=(float(estimate-half),float(estimate+half))
        output.append(dict(outcome=outcome,n_pair=n,n_pair_missing=len(pairs)-n,estimate=estimate,
            high_mean=float(high.mean()),low_mean=float(low.mean()),ci_low=ci[0],ci_high=ci[1],
            n_block=len(set(labels[0])),n_year=len(set(labels[1])),n_eff=effective_count(labels[0]),
            status="conditional_descriptive_interval" if ci[0] is not None else "point_estimate_only",
            estimand="matched_high_minus_low_observed_association",
            ci_method="space_year_pair_normal_conditional_on_match",
            limitation="not_population_ATT;does_not_include_matching_selection_uncertainty"))
    return output


def psm_analysis(events, exposures, blocks, params):
    """条件A内先匹配，再逐结局完整配对；未知FR不参与FR差值。"""
    from src.M7.scr_psm_design import match_design
    if params["psm"]["output_scope"] != "conditional_matched_association":
        raise ValueError("当前PSM仅支持固定匹配样本的条件关联，未实现总体ATT推断。")
    if params["psm"]["common_support_refit_max"] not in (0, 1):
        raise ValueError("共同支撑重拟合仅允许0或1次。")
    exposure = {row["episode_id"]: row for row in exposures}
    rows = [dict(event, **{k:v for k,v in exposure.get(event["episode_id"], {}).items()
                          if k not in event}) for event in events if event["route1_A_eligible"]
            and exposure.get(event["episode_id"], {}).get("exposure_complete_L")]
    pairs, balance, audit = match_design(rows, params)
    audit.update(n_route1_a=sum(bool(r["route1_A_eligible"]) for r in events),
                 inference_scope="conditional_matched_association_not_population_ATT")
    return {"psm_pairs":pairs, "psm_balance":balance,
            "psm_contrast":matched_contrasts(pairs, rows, blocks, audit, params)}, audit
