"""Q1恢复曲线的双向聚类区间和年份得分乘子敏感性。
作者：Codex。由M7主时间基线调用；输出逐候区间、并集与诊断。
"""
from statistics import NormalDist
import numpy as np
from src.M7.scr_cluster_scores import multiway_covariance, year_score_draws


def add_curve_dependence(output, support, risk, events, blocks, design, params):
    """不改变主点估计/空间bootstrap；并列方法无效时不伪造联合区间。"""
    for row in output:
        row.update(hazard_union_ci_low=None,hazard_union_ci_high=None,
                   cumulative_union_ci_low=None,cumulative_union_ci_high=None,union_status="unavailable")
    support["uncertainty_rows"] = []
    if support.get("coefficients") is None:
        support["dependence_status"] = "no_point_estimate"
        return
    lookup = {e["episode_id"]:e for e in events}
    rows = [r for r in risk if r["at_risk"]]
    if any(lookup[r["episode_id"]].get("year") is None for r in rows):
        support["dependence_status"] = "missing_year_labels"
        return
    step=np.array([r["followup_pentad"]-1 for r in rows])
    x=design[step]
    beta=np.array(support["coefficients"])
    y=np.array([r["recovery_event"] for r in rows],dtype=float)
    years=[lookup[r["episode_id"]]["year"] for r in rows]
    space=[blocks[lookup[r["episode_id"]]["grid_id"]] for r in rows]
    mu=np.exp(x @ beta)
    p=-np.expm1(-mu)
    scores=x*((y-p)*mu/p)[:,None]
    information=x.T @ (x*(mu**2*np.exp(-mu)/p)[:,None])
    covariance, diagnostic=multiway_covariance(information,scores,space,years)
    draws,wild=year_score_draws(beta,information,scores,years,params)
    support.update(dependence_status=diagnostic["status"],two_way_diagnostic=diagnostic,year_wild_diagnostic=wild)
    alpha=params["multiple_testing"]["family_alpha"]
    z=NormalDist().inv_cdf(1-alpha/2)
    valid=np.array([r["n_at_risk"]>0 for r in output])
    full_mu=np.zeros(len(design))
    full_mu[valid]=np.exp(design[valid] @ beta)
    hazard=-np.expm1(-full_mu)
    cumulative=-np.expm1(-np.cumsum(full_mu))
    gradients={"hazard":design*(full_mu*np.exp(-full_mu))[:,None],
               "cumulative":np.cumsum(design*full_mu[:,None],axis=0)*np.exp(-np.cumsum(full_mu))[:,None]}
    wild_values={}
    if draws is not None:
        eta=draws @ design.T
        # 无支撑候不参与输出或数值有效性判断。
        usable=np.isfinite(eta[:,valid]).all(axis=1) & (np.abs(eta[:,valid])<=25).all(axis=1)
        eta=eta[usable]
        m=np.exp(np.where(valid,eta,0.))
        wild_values={"hazard":-np.expm1(-m),"cumulative":-np.expm1(-np.cumsum(m,axis=1))}
        wild["bootstrap_success"]=int(usable.sum())
    for j,row in enumerate(output):
        both=[]
        for quantity,estimate in (("hazard",hazard[j]),("cumulative",cumulative[j])):
            exists=valid[j] if quantity=="hazard" else valid[:j+1].all()
            limits={}
            if exists and covariance is not None and 0<estimate<1:
                g=gradients[quantity][j]/(estimate*(1-estimate))
                variance=float(g @ covariance @ g)
                if variance>0:
                    center=np.log(estimate/(1-estimate))
                    ends=np.array([center-z*np.sqrt(variance),center+z*np.sqrt(variance)])
                    limits["block_year_logit_delta"]=tuple(np.exp(-np.logaddexp(0,-ends)))
            if exists and quantity in wild_values:
                values=wild_values[quantity][:,j]
                if len(values)>=params["infer"]["year_score_bootstrap"]["repetitions"]*params["block"]["bootstrap_min_success_fraction"]:
                    limits["year_wild_score_linearized"]=tuple(np.quantile(values,[alpha/2,1-alpha/2]))
            for method in ("block_year_logit_delta","year_wild_score_linearized"):
                low,high=limits.get(method,(None,None))
                support["uncertainty_rows"].append(dict(followup_pentad=j+1,quantity=quantity,ci_method=method,
                    estimate=float(estimate) if exists else None,ci_low=float(low) if low is not None else None,
                    ci_high=float(high) if high is not None else None,ci_scope="pointwise",n_year=len(set(years)),
                    status="available" if low is not None else "unavailable"))
            boot=(row[f"{quantity}_ci_low"],row[f"{quantity}_ci_high"])
            other=limits.get("block_year_logit_delta")
            available=boot[0] is not None and other is not None
            if available:
                row[f"{quantity}_union_ci_low"]=float(min(boot[0],other[0]))
                row[f"{quantity}_union_ci_high"]=float(max(boot[1],other[1]))
            both.append(available)
        row["union_status"]="available" if all(both) else "unavailable"
