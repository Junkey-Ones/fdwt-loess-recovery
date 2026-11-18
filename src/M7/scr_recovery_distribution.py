"""Q1已恢复条件A事件的区域/地类分布与空间、年份联合区间。
作者：Codex。输入M5事件、M6基线地类、冻结分块和params；统一M7发布。
条件分布不代表含右删失事件的总体恢复分布，后者由恢复风险模型处理。
"""
from collections import defaultdict
import numpy as np
from src.M7.scr_fit_route1_models import dependence, effective_count, intervals
from src.M7.scr_spatial_inference import resampling_label, bootstrap_method


def recovery_distribution(events, exposures, blocks, superblocks, params, *, metrics=("RT", "delta_SMP", "RR")):
    """完整事件随空间块重抽，不要求LAI完整；未知地类单列。"""
    cover = {r["episode_id"]:r.get("land_cover") or "unknown" for r in exposures}
    groups = defaultdict(list)
    for event in events:
        if event["route1_A_eligible"]:
            groups["region", "all"].append(event)
            groups["land_cover", cover.get(event["episode_id"], "unknown")].append(event)
    result = []
    settings = params["infer"]
    alpha = params["multiple_testing"]["family_alpha"]
    for (domain, label), candidates in sorted(groups.items()):
        for metric in metrics:
            rows = [r for r in candidates if r.get(metric) is not None and np.isfinite(r[metric])]
            if not rows:
                continue
            y = np.array([r[metric] for r in rows],dtype=float)
            space = [blocks.get(r["grid_id"]) for r in rows]
            codes = [resampling_label(b,superblocks,params) for b in space]
            complete = None not in codes
            effective = effective_count(codes) if complete else 0.
            allow = (complete and len(y)>=settings["min_n"] and len(set(codes))>=settings["min_blocks"]
                     and effective>=settings["min_n_eff"])
            types = ("median",) if metric == "RT" else ("median", "mean")
            draws = {kind:[] for kind in types}
            if allow:
                block_values = defaultdict(list)
                for value, block in zip(y,codes):
                    block_values[block].append(value)
                arrays = [np.asarray(block_values[b]) for b in sorted(block_values)]
                rng = np.random.default_rng(params["random"]["seed"])
                for _ in range(params["block"]["bootstrap_n"]):
                    selected = rng.integers(len(arrays),size=len(arrays))
                    sample = np.concatenate([arrays[i] for i in selected])
                    draws["median"].append(float(np.median(sample)))
                    if "mean" in draws:
                        draws["mean"].append(float(np.mean(sample)))
            for kind in types:
                estimate = float(np.median(y) if kind=="median" else np.mean(y))
                # RT为整数候，中位数不使用连续密度近似的正态聚类区间。
                covariance = (dependence(rows,np.ones((len(y),1)),y,np.array([estimate]),kind,space)
                              if allow and metric != "RT" else None)
                se = float(np.sqrt(covariance[0,0])) if covariance is not None and covariance[0,0]>0 else None
                boot, two_way, union = intervals(estimate,draws[kind],se,alpha)
                discrete_status=None
                if metric=="RT" and allow:
                    from src.M7.scr_discrete_median_interval import discrete_median_interval
                    two_way,discrete_status=discrete_median_interval(y,space,[r["year"] for r in rows],params)
                    if None not in (*boot,*two_way):
                        union=(min(boot[0],two_way[0]),max(boot[1],two_way[1]))
                result.append(dict(domain=domain,domain_id=label,metric=metric,statistic=kind,
                    n_candidate=len(candidates),n_event=len(y),n_missing=len(candidates)-len(y),
                    n_block=len(set(codes)) if complete else None,n_eff=effective,n_year=len({r["year"] for r in rows}),
                    estimate=estimate,q25=float(np.quantile(y,.25)),q75=float(np.quantile(y,.75)),
                    bootstrap_ci_low=boot[0],bootstrap_ci_high=boot[1],block_year_ci_low=two_way[0],
                    block_year_ci_high=two_way[1],ci_low=union[0],ci_high=union[1],
                    bootstrap_success=len(draws[kind]),bootstrap_requested=params["block"]["bootstrap_n"],
                    bootstrap_method=bootstrap_method(params),ci_method=("space_bootstrap_union_cdf_inversion" if metric=="RT"
                        else "union") if union[0] is not None else None,
                    status="available" if union[0] is not None else "spatial_interval_only" if boot[0] is not None else "point_estimate_only",
                    limitation=discrete_status if metric=="RT" else None,
                    population="recovered_route1_A_conditional"))
    return result
