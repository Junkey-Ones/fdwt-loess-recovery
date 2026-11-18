"""E1a格点年计数及负二项区域频率补充模型。
作者：Codex。输入M3候表/掩膜、M5事件和M2空间块；输出M7探索表。
统一入口调用，零事件年保留，未知不当作零；不修改主检验。
"""
from collections import Counter, defaultdict
from math import isfinite
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln
from src.M7.scr_cluster_scores import multiway_covariance
from src.M7.scr_fit_route1_models import effective_count, intervals
from src.M7.scr_spatial_inference import resampling_label


def count_grid_years(batches, masks, events, blocks, params, report=None):
    """按完整活跃窗构造计数分母，保留零年和所有排除原因。"""
    if params["route1"]["e1a"]["support"] != "complete_active_window":
        raise ValueError("未实现的E1a观测支撑规则。")
    included = {r["grid_id"] for r in masks if r["mask_include"]}
    states = {}
    done=0
    for batch in batches:
        for row in batch.to_pylist():
            if row["grid_id"] not in included:
                continue
            state = states.setdefault((row["grid_id"],row["year"]),dict(L=None,active=0,valid=0))
            length = row.get("active_window_length_L")
            if length is not None:
                if state["L"] is not None and state["L"] != length:
                    raise ValueError("E1a同一格点年的活跃窗长度不唯一。")
                state["L"] = length
            if row.get("active_flag") is True:
                state["active"] += 1
                state["valid"] += (row.get("p95_usable") is True and all(row.get(k) is not None and
                                   isfinite(row[k]) for k in ("smp","p_mm")))
        done+=batch.num_rows
        if report:report("构建E1a分母",f"已核对{done}条格点候记录")
    counts, unknown, unresolved = Counter(), Counter(), Counter()
    for event in events:
        key = event["grid_id"],event["year"]
        if event.get("recovery_risk_eligible") and event.get("t_e") is None:
            unresolved[key] += 1
        if event["route1_FR_eligible"]:
            if event["F_R"] is None:
                unknown[key] += 1
            else:
                counts[key] += int(event["F_R"])
    output = []
    for grid in sorted(included):
        for year in range(params["time"]["year_start"],params["time"]["year_end"]+1):
            state = states.get((grid,year),dict(L=None,active=0,valid=0))
            reason = ("missing_active_window" if not state["L"] else
                      "incomplete_active_observations_or_threshold" if state["active"]!=state["L"] or state["valid"]!=state["L"] else
                      "unknown_fr_window" if unknown[grid,year] else
                      "unresolved_terminal_event" if unresolved[grid,year] else
                      "missing_block" if blocks.get(grid) is None else None)
            output.append(dict(grid_id=grid,year=year,block_id=blocks.get(grid),L=state["L"],
                n_active=state["active"],n_valid=state["valid"],n_fr_known=counts[grid,year],
                n_unknown=unknown[grid,year],n_unresolved=unresolved[grid,year],included=reason is None,
                exclusion_reason=reason,rate=counts[grid,year]/state["L"] if reason is None else None))
    return output


def fit_nb2(x, y, offset, weights, params):
    """固定频率权重的NB2最大似然；数值界内估计alpha并标记边界。"""
    keep = weights>0
    x,y,offset,w = x[keep],y[keep],offset[keep],weights[keep]
    if not np.isfinite(y).all() or np.any(y<0) or np.any(y!=np.floor(y)):
        raise ValueError("NB2结局必须为有限非负整数计数。")
    if not len(y) or np.linalg.matrix_rank(x)<x.shape[1] or np.sum(w*y)==0:
        return None,"insufficient_support",None
    lo,hi=params["route1"]["e1a"]["dispersion_bounds"]
    beta=np.zeros(x.shape[1]);beta[0]=np.log(np.sum(w*y)/np.sum(w*np.exp(offset)))
    initial=np.r_[beta,np.log(np.clip(1.,lo,hi))]

    def objective(value):
        eta=offset+x @ value[:-1]
        if np.max(np.abs(eta))>100:
            return np.inf,np.zeros(len(value))
        mu=np.exp(eta);a=np.exp(value[-1]);theta=1/a
        # 计数为整数；改写上升阶乘避免Poisson极限下两个巨大gammaln相减。
        rising=np.zeros(len(y));rising_score=np.zeros(len(y))
        for k in range(1,int(y.max())):
            mask=y>k
            rising[mask]+=np.log1p(a*k)
            rising_score[mask]+=a*k/(1+a*k)
        z=a*mu
        ll=rising-gammaln(y+1)+y*eta-(y+theta)*np.log1p(z)
        score=x.T @ (w*(y-mu)/(1+a*mu))
        dispersion_score=rising_score+(np.log1p(z)-z/(1+z))/a-y*z/(1+z)
        return -float(w @ ll),np.r_[-score,-np.sum(w*dispersion_score)]

    fitted=minimize(objective,initial,jac=True,method="L-BFGS-B",
                    bounds=[(None,None)]*x.shape[1]+[(np.log(lo),np.log(hi))],
                    options={"maxiter":2000,"ftol":1e-12,"gtol":1e-7})
    # technical constant：用每条频率单位的梯度检查数值最优性。
    gradient=objective(fitted.x)[1]
    if not fitted.success or not np.isfinite(fitted.x).all() or np.max(np.abs(gradient[:-1]))/w.sum()>1e-6:
        return None,"nonconverged",None
    alpha=float(np.exp(fitted.x[-1]))
    if alpha>=hi*(1-1e-6):
        return None,"dispersion_upper_boundary",alpha
    return fitted.x[:-1],"poisson_limit" if alpha<=lo*(1+1e-5) else "fitted",alpha


def fit_frequency(rows, superblocks, params, report=None):
    """压缩相同(year,L,count)充分记录，以固定空间块频率权重自举。"""
    if params["route1"]["e1a"]["terms"] != ["intercept","year"]:
        raise ValueError("E1a仅实现已登记的区域频率年份描述公式。")
    sample=[r for r in rows if r["included"]]
    labels=[resampling_label(r["block_id"],superblocks,params) for r in sample]
    years=[r["year"] for r in sample]
    audit=dict(n_grid_year=len(sample),n_before=len(rows),n_zero=sum(r["n_fr_known"]==0 for r in sample),
               n_positive=sum(r["n_fr_known"]>0 for r in sample),n_block=len(set(labels)),
               n_year=len(set(years)),n_eff=effective_count(labels),status="insufficient_support",
               formula="log(E[N_FR])=log(L)+intercept+year_slope*(year-year_mean)")
    minimum=params["infer"]
    if (len(sample)<minimum["min_n"] or audit["n_eff"]<minimum["min_n_eff"] or
        audit["n_block"]<minimum["min_blocks"] or min(audit["n_zero"],audit["n_positive"])<minimum["min_event_per_arm"]):
        return [],audit
    keys=sorted({(r["year"],r["L"],r["n_fr_known"]) for r in sample})
    key_id={k:i for i,k in enumerate(keys)};block_id={b:i for i,b in enumerate(sorted(set(labels)))}
    frequency=np.zeros((len(block_id),len(keys)))
    for r,b in zip(sample,labels):frequency[block_id[b],key_id[r["year"],r["L"],r["n_fr_known"]]]+=1
    center=float(np.mean(years))
    x=np.array([[1.,year-center] for year,_,_ in keys]);offset=np.log([L for _,L,_ in keys]);y=np.array([n for _,_,n in keys])
    beta,status,dispersion=fit_nb2(x,y,offset,frequency.sum(axis=0),params)
    audit.update(status=status,dispersion=dispersion,year_center=center)
    if beta is None:return [],audit
    positions=np.array([key_id[r["year"],r["L"],r["n_fr_known"]] for r in sample])
    design=x[positions];observed=y[positions];mu=np.exp(offset[positions]+design @ beta)
    score=design*((observed-mu)/(1+dispersion*mu))[:,None]
    information=design.T @ (design*(mu/(1+dispersion*mu))[:,None])
    covariance,diagnostic=multiway_covariance(information,score,labels,years)
    audit["two_way_diagnostic"]=diagnostic
    rng=np.random.default_rng(params["random"]["seed"]);draws=[];failures=Counter();boundaries=0
    requested=params["block"]["bootstrap_n"]
    for i in range(requested):
        multiplicities=np.bincount(rng.integers(len(block_id),size=len(block_id)),minlength=len(block_id))
        draw,reason,_=fit_nb2(x,y,offset,multiplicities @ frequency,params)
        if draw is None:failures[reason]+=1
        else:
            draws.append(draw);boundaries+=reason=="poisson_limit"
        if report and i%10==0:report("E1a空间自举",f"成功{len(draws)}次",done=i,total=requested,unit="次")
    audit.update(bootstrap_success=len(draws),bootstrap_requested=requested,bootstrap_failures=dict(failures),
                 bootstrap_poisson_limit=boundaries)
    if report:report("E1a空间自举",f"成功{len(draws)}次",done=requested,total=requested,unit="次")
    usable=len(draws)>=requested*params["block"]["bootstrap_min_success_fraction"]
    output=[]
    for j,term in enumerate(("intercept","year_slope")):
        se=float(np.sqrt(covariance[j,j])) if covariance is not None and covariance[j,j]>0 else None
        boot,cluster,union=intervals(float(beta[j]),[d[j] for d in draws] if usable else [],se,params["multiple_testing"]["family_alpha"])
        output.append(dict(term=term,estimate=float(beta[j]),scale="log_frequency_per_active_pentad",
            dispersion=dispersion,bootstrap_ci_low=boot[0],bootstrap_ci_high=boot[1],
            block_year_ci_low=cluster[0],block_year_ci_high=cluster[1],ci_low=union[0],ci_high=union[1],
            status="exploratory_interval" if union[0] is not None else "point_estimate_only",
            ci_method="union" if union[0] is not None else None))
    return output,audit
