"""Q2/Q3年份簇得分bootstrap系数敏感性，不替代主检验。
作者：Codex。输入固定设计/点估计/年份；M7输出独立敏感性表。
"""
import numpy as np
from src.M7.scr_cluster_scores import year_score_draws


def coefficient_year_sensitivity(analysis, names, design, outcome, beta, family, years, params, weights=None):
    """与主模型采用同一得分及信息近似，按年份簇生成独立区间。"""
    eta=design @ beta
    if family=="logit":
        p=np.exp(-np.logaddexp(0,-eta))
        score, weight=outcome-p,p*(1-p)
    elif family=="cloglog":
        mu=np.exp(np.clip(eta,-25,25));p=-np.expm1(-mu)
        score,weight=(outcome-p)*mu/p,mu**2*np.exp(-mu)/p
    elif family=="median":
        residual=outcome-eta
        spread=min(np.std(residual,ddof=1),np.subtract(*np.quantile(residual,[.75,.25]))/1.349)
        bandwidth=.9*spread*len(residual)**(-.2)
        if not bandwidth:
            return [dict(analysis_id=analysis,term=name,status="zero_residual_bandwidth",
                         ci_method="year_wild_score_linearized",n_year=len(set(years))) for name in names]
        score=.5-(residual<0)
        weight=np.exp(-.5*(residual/bandwidth)**2)/(np.sqrt(2*np.pi)*bandwidth)
    elif family=="mean":
        score,weight=outcome-eta,np.ones(len(outcome))
    else:
        raise ValueError(f"未实现年份得分敏感性模型：{family}")
    if weights is not None:
        score,weight=score*weights,weight*weights
    information=design.T @ (design*weight[:,None])
    draws,audit=year_score_draws(beta,information,design*score[:,None],years,params)
    alpha=params["multiple_testing"]["family_alpha"]
    if draws is not None:
        draws=draws[np.isfinite(draws).all(axis=1)]
    minimum=params["infer"]["year_score_bootstrap"]["repetitions"]*params["block"]["bootstrap_min_success_fraction"]
    usable=draws is not None and len(draws)>=minimum
    return [dict(analysis_id=analysis,term=name,estimate=float(beta[i]),
                 ci_low=float(np.quantile(draws[:,i],alpha/2)) if usable else None,
                 ci_high=float(np.quantile(draws[:,i],1-alpha/2)) if usable else None,
                 ci_method="year_wild_score_linearized",n_year=audit["n_year"],
                 bootstrap_requested=params["infer"]["year_score_bootstrap"]["repetitions"],
                 bootstrap_success=len(draws) if draws is not None else 0,
                 status="available" if usable else ("insufficient_bootstrap" if draws is not None else audit["status"]),
                 inference_scope="asymptotic_sensitivity_only") for i,name in enumerate(names)]
