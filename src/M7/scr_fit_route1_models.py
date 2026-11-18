"""脚本名：scr_fit_route1_models.py（M7 · Q2／Q3 回归）
功能简介：拟合事件级 logit、中位数回归和事件—候 cloglog。
作者：Codex
版本：v0.1.0
读取数据：M5 事件、M6 暴露、M7 风险集和空间块。
生成数据：M7 冻结模型清单、系数和边际预测。
其他文件：统一入口写入运行回执与日志。
运行示例：python -m workflow.run_module M7 --run-alias 2026-11-13_主分析
退出码：由统一入口定义。
"""
from collections import Counter, defaultdict
from math import erfc, sqrt
import json

import numpy as np

from src.M7.scr_fit_recovery_risk import fit_grouped_cloglog, natural_spline
from src.M7.scr_fit_median import fit_weighted_median
from src.M7.scr_route1_summary import holm
from src.M7.scr_spatial_inference import bootstrap_method, resampling_label, resampling_scheme


def logistic(eta):
    """计算稳定的逆 logit。"""
    return np.exp(-np.logaddexp(0, -eta))


def fit_coefficients(x, y, w, family):
    """在固定设计上拟合模型，返回系数或明确的失败状态。"""
    keep = w > 0
    x, y, w = x[keep], y[keep], w[keep]
    if not len(y) or np.linalg.matrix_rank(x) < x.shape[1]:
        return None, "rank_deficient"
    if family == "cloglog":
        return fit_grouped_cloglog(x, w, w*y)
    if family == "logit":
        return fit_binomial_logit(x, y, w)
    if family == "mean":
        root = np.sqrt(w)
        beta = np.linalg.lstsq(x*root[:, None], y*root, rcond=None)[0]
        return (beta, "fitted") if np.isfinite(beta).all() else (None, "nonfinite")
    if family != "median":
        raise ValueError(f"未登记的回归族：{family}")
    beta, status, _ = fit_weighted_median(x, y, w)
    return beta, status


def fit_binomial_logit(x, y, w):
    """以加权二项似然和步长回退拟合 logit。"""
    p = np.average(y, weights=w)
    if not 0 < p < 1:
        return None, "no_outcome_variation"
    beta = np.zeros(x.shape[1])
    beta[0] = np.log(p/(1-p))

    def likelihood(eta):
        return np.sum(w*(y*eta-np.logaddexp(0, eta)))

    for _ in range(100):
        eta = x @ beta
        p = logistic(eta)
        info = x.T @ (x*(w*p*(1-p))[:, None])
        if np.linalg.matrix_rank(info) < x.shape[1]:
            return None, "singular_information_possible_separation"
        score = x.T @ (w*(y-p))
        direction = np.linalg.solve(info, score)
        baseline = likelihood(eta)
        for power in range(21):
            step = direction/(2**power)
            candidate = beta + step
            if likelihood(x @ candidate) >= baseline - 1e-10:
                beta = candidate
                break
        else:
            return None, "nonconverged"
        if np.max(abs(beta)) > 50:
            return None, "possible_separation"
        if np.max(abs(step)) < 1e-8 and np.max(abs(score)) < 1e-6:
            return beta, "fitted"
    return None, "nonconverged"


def design_matrix(rows, terms, core):
    """按事件等权标准化连续变量，以固定地类作参照。"""
    names, columns, scales = ["intercept"], [np.ones(len(rows))], {}
    for name in [*terms, *core]:
        if name in ("land_cover", "year_factor"):
            levels = sorted({row[name] for row in rows})
            for level in levels[1:]:
                names.append(f"{name}[{level}]")
                columns.append(np.array([row[name] == level for row in rows], dtype=float))
            continue
        values = np.array([row[name] for row in rows], dtype=float)
        if name != "fr_pre_sync":
            center, scale = float(values.mean()), float(values.std(ddof=1)) if len(values) > 1 else 0.0
            if not scale:
                if name in terms:
                    return None, None, {}
                continue
            scales[name] = (center, scale)
            values = (values-center)/scale
        names.append(name)
        columns.append(values)
    if "LAI_trend" in terms and "deep_SM_pre4_percentile" in terms:
        names.append("LAI_trend_x_deep")
        columns.append(columns[names.index("LAI_trend")]*columns[names.index("deep_SM_pre4_percentile")])
    return names, np.column_stack(columns), scales


def dependence(rows, design, outcome, beta, family, blocks, weights=None):
    """以空间和年份的交叉聚类得分估计协方差。"""
    eta = design @ beta
    if family == "logit":
        p = logistic(eta)
        score, information = outcome-p, p*(1-p)
    elif family == "cloglog":
        mu = np.exp(np.clip(eta, -25, 25))
        p = -np.expm1(-mu)
        score, information = (outcome-p)*mu/p, mu**2*np.exp(-mu)/p
    elif family == "mean":
        score, information = outcome-eta, np.ones(len(outcome))
    else:
        residual = outcome-eta
        spread = min(np.std(residual, ddof=1), np.subtract(*np.quantile(residual, [.75, .25]))/1.349)
        bandwidth = 0.9*spread*len(residual)**(-0.2)
        if not bandwidth:
            return None
        score = 0.5-(residual < 0)
        information = np.exp(-0.5*(residual/bandwidth)**2)/(sqrt(2*np.pi)*bandwidth)
    if weights is not None:
        score, information = score*weights, information*weights
    bread = design.T @ (design*information[:, None])
    if np.linalg.matrix_rank(bread) < len(beta):
        return None
    inverse = np.linalg.inv(bread)
    years = [row["year"] for row in rows]
    meats = []
    scores = design*score[:, None]
    for labels in (blocks, years, zip(blocks, years)):
        groups = defaultdict(lambda: np.zeros(len(beta)))
        for label, value in zip(labels, scores):
            groups[label] += value
        if len(groups) < 2:
            return None
        clustered = np.stack(list(groups.values()))
        meats.append((clustered.T @ clustered)*len(groups)/(len(groups)-1))
    return inverse @ (meats[0]+meats[1]-meats[2]) @ inverse


def margins(names, x, beta, family, time, deep_levels, weights=None):
    """计算 LAI 相差一个样本标准差时的平均预测和差值。"""
    lai = names.index("LAI_trend")
    deep = names.index("deep_SM_pre4_percentile")
    interaction = names.index("LAI_trend_x_deep")
    output = []
    for level in deep_levels:
        predictions = []
        for exposure in (0.0, 1.0):
            changed = x.copy()
            changed[:, [lai, deep, interaction]] = (exposure, level, exposure*level)
            eta = changed @ beta[:x.shape[1]]
            if family == "cloglog":
                baseline = time @ beta[x.shape[1]:]
                cumulative = np.exp(np.clip(eta, -50, 50))*np.exp(baseline).sum()
                predictions.append(float(np.average(-np.expm1(-cumulative), weights=weights)))
            else:
                predictions.append(float(np.average(eta if family in ("median", "mean") else logistic(eta), weights=weights)))
        output.append([*predictions, predictions[1]-predictions[0]])
    return np.array(output)


def effective_count(labels):
    """计算按簇大小的 Kish 保守有效计数。"""
    sizes = Counter(labels)
    n = sum(sizes.values())
    return n*n/sum(size*size for size in sizes.values()) if n else 0.0


def intervals(estimate, draws, se, alpha):
    """返回 bootstrap、双向聚类和涵盖两者的推断区间。"""
    from statistics import NormalDist

    boot = tuple(map(float, np.quantile(draws, [alpha/2, 1-alpha/2]))) if len(draws) else (None, None)
    critical = NormalDist().inv_cdf(1-alpha/2)
    cluster = (estimate-critical*se, estimate+critical*se) if se is not None else (None, None)
    combined = (min(boot[0], cluster[0]), max(boot[1], cluster[1])) if None not in (*boot, *cluster) else (None, None)
    return boot, cluster, combined


def summarize_fr_support(events, blocks, superblocks, params):
    """输出格点—年 E1b 计数和区域、分块 F_R 条件比例。"""
    grid_year, groups = {}, defaultdict(list)
    for row in events:
        if not row["route1_A_eligible"]:
            continue
        grid, year = row["grid_id"], row["year"]
        block = blocks.get(grid)
        item = grid_year.setdefault((grid, year), dict(grid_id=grid, year=year, block_id=block,
                                  n_a=0, n_known=0, n_positive=0, n_unknown=0, n_outside_active_window=0))
        item["n_a"] += 1
        if not row["route1_FR_eligible"]:
            item["n_outside_active_window"] += 1
        elif row["F_R"] is None:
            item["n_unknown"] += 1
        else:
            item["n_known"] += 1
            item["n_positive"] += int(row["F_R"])
    for item in grid_year.values():
        item["proportion"] = item["n_positive"]/item["n_known"] if item["n_known"] else None
        groups[("region", "all")].append(item)
        if item["block_id"] is not None:
            groups[("block", str(item["block_id"]))].append(item)
    summaries = []
    for (domain, key), items in sorted(groups.items()):
        counts = {name: sum(row[name] for row in items) for name in
                  ("n_a", "n_known", "n_positive", "n_unknown", "n_outside_active_window")}
        n = counts["n_known"]
        result = dict(domain=domain, domain_id=key, **counts, proportion=counts["n_positive"]/n if n else None,
                      ci_low=None, ci_high=None)
        totals = defaultdict(lambda: np.zeros(2, dtype=int))
        for row in items:
            if row["block_id"] is not None and row["n_known"]:
                totals[resampling_label(row["block_id"], superblocks, params)] += (row["n_positive"], row["n_known"])
        result["n_superblock"] = len({superblocks.get(row["block_id"], row["block_id"])
                                     for row in items if row["block_id"] is not None and row["n_known"]})
        result["n_resampling_block"] = len(totals)
        result["ci_method"] = bootstrap_method(params)
        if len(totals) >= params["infer"]["min_blocks"] and sum(x[1] for x in totals.values()) == n:
            rng = np.random.default_rng(params["random"]["seed"])
            counts_by_block = np.stack(list(totals.values()))
            draws = []
            for _ in range(params["block"]["bootstrap_n"]):
                positive, denominator = counts_by_block[rng.integers(len(totals), size=len(totals))].sum(axis=0)
                draws.append(positive/denominator)
            alpha = params["multiple_testing"]["family_alpha"]
            result["ci_low"], result["ci_high"] = map(float, np.quantile(draws, [alpha/2, 1-alpha/2]))
        summaries.append(result)
    return list(grid_year.values()), summaries


def lag_intervals(events, lag_summary, blocks, superblocks, params):
    """按配置的空间抽样单元计算候差中位数区间，保留原连接诊断。"""
    rng = np.random.default_rng(params["random"]["seed"])
    alpha = params["multiple_testing"]["family_alpha"]
    for summary in lag_summary:
        metric = summary["metric"]
        groups = defaultdict(list)
        diagnostic_blocks = set()
        for row in events:
            include = row["P_term"] is True if metric == "Lag_P" else (
                row["route1_FR_eligible"] and row["F_R"] is True)
            block = blocks.get(row["grid_id"])
            if include and block is not None:
                groups[resampling_label(block, superblocks, params)].append(row[metric])
                diagnostic_blocks.add(superblocks.get(block, block))
        summary.update(ci_low=None, ci_high=None, n_superblock=len(diagnostic_blocks),
                       n_resampling_block=len(groups), ci_method=bootstrap_method(params))
        if len(groups) < params["infer"]["min_blocks"] or sum(map(len, groups.values())) != summary["n_event"]:
            continue
        arrays = [np.asarray(groups[key]) for key in sorted(groups)]
        draws = []
        for _ in range(params["block"]["bootstrap_n"]):
            sampled = rng.integers(len(arrays), size=len(arrays))
            draws.append(np.median(np.concatenate([arrays[i] for i in sampled])))
        summary["ci_low"], summary["ci_high"] = map(float, np.quantile(draws, [alpha/2, 1-alpha/2]))


def fit_route1_models(events, exposures, risk, blocks, superblocks, params, identity, report=None,
                      *, selection=None, exploratory=False, sample_mode="event"):
    """拟合冻结的 Q2／Q3 主模型，保留门槛、区间和家族检验。"""
    by_id = {row["episode_id"]: row for row in exposures}
    histories = defaultdict(list)
    for row in risk:
        if row["at_risk"]:
            histories[row["episode_id"]].append(row)
    core = params["covariates"]["core"]
    rows = [{**event, **by_id[event["episode_id"]]} for event in events]
    if "year_factor" in core:
        rows = [dict(row, year_factor=row["year"]) for row in rows]
    fr = [row for row in rows if row["route1_FR_eligible"] and row["F_R"] is not None]
    contrast = [dict(row, fr_pre_sync=int(row["F_R"])) for row in fr
                if not row["F_R"] or row["F_R_subtype"] in ("pre", "sync")]
    models = [("q2_fr", "Q2", "logit", "F_R", [], fr, None),
              *[(f"q2_{outcome}", "Q2", "median", outcome, ["fr_pre_sync"], contrast,
                 f"fr_pre_sync_{outcome.lower()}_contrast") for outcome in ("RR", "delta_SMP")]]
    if selection == "q2_mean":
        models = [(f"q2_{outcome}_mean", "Q2", "mean", outcome, ["fr_pre_sync"], contrast, None)
                  for outcome in ("RR", "delta_SMP")]
    for domain, family, outcome, sample in (("recovery_risk", "cloglog", "recovery_event", rows),
                                             ("fr", "logit", "F_R", fr)):
        for model, terms in (("L", ["LAI_trend", "LAI_base"]), ("D", ["deep_SM_pre4_percentile"]),
                             ("I", ["LAI_trend", "LAI_base", "deep_SM_pre4_percentile"])):
            test = {"L": f"lai_trend_{domain}", "I": f"lai_trend_deep_{domain}"}.get(model)
            models.append((f"q3_{domain}_{model}", "Q3", family, outcome, terms,
                           [row for row in sample if row[f"exposure_complete_{model}"]], test))
    if selection == "q3_continuous":
        models = [(f"q3_{outcome}_{model}", "Q3", "median", outcome, terms,
                   [r for r in rows if r["route1_A_eligible"] and r[f"exposure_complete_{model}"]], None)
                  for outcome in ("RR", "delta_SMP")
                  for model, terms in (("L", ["LAI_trend", "LAI_base"]), ("D", ["deep_SM_pre4_percentile"]),
                                       ("I", ["LAI_trend", "LAI_base", "deep_SM_pre4_percentile"]))]
    manifests, coefficients, marginal, uncertainty, year_sensitivity = [], [], [], [], []
    for spec in models:
        if selection == "q2_mean" and spec[1] != "Q2":
            continue
        if selection == "q3" and spec[1] != "Q3":
            continue
        if selection == "q3_lai" and (spec[1] != "Q3" or spec[0].endswith("_D")):
            continue
        if selection == "fr_only" and not (spec[2] == "logit" and spec[3] == "F_R"):
            continue
        if selection == "q3_recovery" and not spec[0].startswith("q3_recovery_"):
            continue
        if exploratory:
            spec = (*spec[:-1], None)
        if report:
            report("拟合预设模型", spec[0])
        fit_one_model(spec, histories, core, blocks, superblocks, params, identity,
                      manifests, coefficients, marginal, uncertainty, report=report,
                      year_sensitivity=year_sensitivity, sample_mode=sample_mode)
    if exploratory:
        for row in manifests:
            if row["inference_level"] == "formal":
                row["inference_level"] = "sensitivity_interval"
    for family, tests in params["multiple_testing"]["families"].items():
        lookup = {row["test_id"]: row for row in coefficients if row.get("test_family") == family}
        for test, p in zip(tests, holm([lookup.get(test, {}).get("p_raw") for test in tests])):
            if test in lookup:
                lookup[test]["p_holm"] = p
    return {"model_fit_manifest": manifests, "model_result": coefficients, "model_marginal": marginal,
            "route1_model_uncertainty": uncertainty, "route1_year_wild_sensitivity": year_sensitivity}


def fit_one_model(spec, histories, core, blocks, superblocks, params, identity,
                  manifests, coefficients, marginal, uncertainty, report=None, year_sensitivity=None,
                  sample_mode="event"):
    """执行单个预设模型及其两个依赖性区间。"""
    analysis, question, family, outcome, terms, candidates, test = spec
    rows = [row for row in candidates if blocks.get(row["grid_id"]) is not None
            and all((v := row.get(key)) is not None and
                    (isinstance(v, str) and bool(v) if key == "land_cover" else np.isfinite(v))
                    for key in [*terms, *core])
            and (bool(histories.get(row["episode_id"])) if family == "cloglog"
                 else row.get(outcome) is not None and np.isfinite(row[outcome]))]
    if sample_mode == "common_sample":
        rows = [r for r in rows if all(r.get(f"exposure_complete_{m}") for m in ("L", "D", "I"))]
    if sample_mode == "one_per_exposure":
        groups = defaultdict(list)
        for row in rows:
            groups[row["LAI_exposure_cluster"]].append(row)
        if None in groups:
            raise ValueError("暴露簇抽样缺少格点×年份标签。")
        rng = np.random.default_rng(params["random"]["seed"])
        rows = [ordered[int(rng.integers(len(ordered)))] for key in sorted(groups)
                for ordered in [sorted(groups[key], key=lambda r: r["episode_id"])]]
    if sample_mode not in ("event", "common_sample", "one_per_exposure", "inverse_exposure"):
        raise ValueError(f"未登记的事件抽样模式：{sample_mode}")
    labels = [blocks[row["grid_id"]] for row in rows]
    spatial = [resampling_label(block, superblocks, params) for block in labels]
    lai_clusters = [row["LAI_exposure_cluster"] for row in rows] if "LAI_trend" in terms else []
    cluster_sizes = list(Counter(lai_clusters).values())
    n = len(rows)
    years = [row["year"] for row in rows]
    status = dict(analysis_id=analysis, question=question, estimand=analysis,
                  model_family=family, model_code=analysis.rsplit("_", 1)[-1], outcome=outcome,
                  exposure_version="lai_four_of_five" if identity.get("variant") == "lai_four_of_five" else "main",
                  n_event=n, n_before=len(candidates),
                  n_block=len(set(labels)),
                  n_superblock=len({superblocks.get(block, block) for block in labels}),
                  n_resampling_block=len(set(spatial)), n_year=len(set(years)),
                  resampling_unit=resampling_scheme(params),
                  support_count_basis="min_event_resampling_kish_exposure_kish",
                  n_exposure=len(cluster_sizes) if "LAI_trend" in terms else None,
                  cluster_size_median=float(np.median(cluster_sizes)) if cluster_sizes else None,
                  cluster_size_p95=float(np.quantile(cluster_sizes, .95)) if cluster_sizes else None,
                  cluster_size_max=max(cluster_sizes, default=None),
                  max_cluster_share=max(cluster_sizes)/n if cluster_sizes else None,
                  sample_start_year=min(years, default=None), sample_end_year=max(years, default=None),
                  link_function=family if family not in ("median", "mean") else "identity",
                  convergence_status="not_attempted", support_gate="insufficient_support",
                  inference_level="descriptive_only", random_seed_id=params["random"]["seed_id"],
                  run_id=identity.get("run_id"), code_hash=identity.get("code_hash"))
    manifests.append(status)
    cover_blocks = defaultdict(set)
    if "land_cover" in core:
        for row, block in zip(rows, spatial):
            cover_blocks[row["land_cover"]].add(block)
    status["land_cover_block_counts"] = json.dumps({k: len(v) for k, v in sorted(cover_blocks.items())})
    n_spatial = len(set(spatial))
    ceiling = min((1 - (1-len(v)/n_spatial)**n_spatial for v in cover_blocks.values()), default=1.)
    status["bootstrap_category_support_ceiling"] = ceiling if n_spatial else None
    status["inference_warning"] = ("地类集中于少数空间块；缺类抽样将秩亏，自举成功率可能不足"
        if cover_blocks and ceiling < params["block"]["bootstrap_min_success_fraction"] else None)
    term = "fr_pre_sync" if question == "Q2" else "LAI_trend_x_deep" if analysis.endswith("_I") else "LAI_trend"
    if test:
        coefficients.append(dict(analysis_id=analysis, term=term, scale="link" if family != "median" else "original",
                                 test_family=question.lower(), test_id=test))
    if not rows:
        return
    if any(label is None for label in lai_clusters):
        raise ValueError("完整 LAI 暴露案例缺少格点—年暴露簇。")
    for key in ("product", "definition_id", "support_id"):
        values = {row.get(key) for row in rows}
        if len(values) != 1:
            raise ValueError(f"路线一单模型混合多个 {key}：{analysis}")
        status[key] = values.pop()
    continuous_exposure = family in ("median", "mean") and "fr_pre_sync" not in terms
    if continuous_exposure:
        arms = [True]*n
    elif family == "cloglog":
        arms = [any(r["recovery_event"] for r in histories[row["episode_id"]]) for row in rows]
    else:
        arms = [bool(row["fr_pre_sync" if family in ("median", "mean") else outcome]) for row in rows]
    positive = sum(arms)
    n_eff = min(n, effective_count(spatial), effective_count(lai_clusters) if lai_clusters else n)
    status.update(n_outcome=None if continuous_exposure else positive,
                  n_nonoutcome=None if continuous_exposure else n-positive, n_eff=float(n_eff))
    settings = params["infer"]
    if (n < settings["min_n"] or n_eff < settings["min_n_eff"] or
            len(set(spatial)) < settings["min_blocks"] or
            (not continuous_exposure and min(positive, n-positive) < settings["min_event_per_arm"])):
        return
    names, x, scales = design_matrix(rows, terms, core)
    if x is None:
        status["convergence_status"] = "constant_exposure"
        return
    horizon = params["route1"]["recovery_risk_h"]
    time = natural_spline(range(1, horizon+1), horizon)[:, 1:] if family == "cloglog" else None
    if family == "cloglog" and params["route1"]["recovery_time_df"] != time.shape[1]:
        raise ValueError("Q3 恢复风险时间样条自由度与冻结配置不符。")
    if family == "cloglog":
        event_index, step, values = zip(*[(i, r["followup_pentad"], r["recovery_event"])
                                         for i, row in enumerate(rows) for r in histories[row["episode_id"]]])
        event_index = np.asarray(event_index)
        design = np.column_stack((x[event_index], time[np.asarray(step)-1]))
        y = np.asarray(values, dtype=float)
    else:
        event_index = np.arange(n)
        design = x
        y = np.array([row[outcome] for row in rows], dtype=float)
    status["outcome_sd"] = float(np.std(y, ddof=1)) if family in ("median", "mean") else None

    def epv(width):
        if continuous_exposure:
            return min(n, len(set(lai_clusters)) if lai_clusters else n)/width
        events_per_term = min(positive, n-positive)/width
        if lai_clusters:
            sizes = Counter(lai_clusters)
            effective_positive = sum(1/sizes[label] for label, arm in zip(lai_clusters, arms) if arm)
            events_per_term = min(events_per_term, effective_positive/width,
                                  (len(sizes)-effective_positive)/width)
        return events_per_term

    width = design.shape[1]
    if family == "cloglog" and (epv(width) < settings["epv_min"] or
                                np.linalg.matrix_rank(design) < width):
        time, design = time[:, :1], design[:, :x.shape[1]+1]
        width = design.shape[1]
    epv_conservative = epv(width)
    status.update(epv=n/width if continuous_exposure else min(positive, n-positive)/width,
                  conservative_epv=epv_conservative)
    if family not in ("median", "mean") and epv_conservative < settings["epv_min"]:
        return
    names += [f"time_{i+1}" for i in range(width-x.shape[1])]
    status.update(formula=f"{outcome} ~ " + " + ".join(names), support_gate="passed")
    event_weights = np.ones(n)
    if sample_mode == "inverse_exposure":
        groups = Counter(r["LAI_exposure_cluster"] for r in rows)
        if None in groups:
            raise ValueError("逆簇大小加权缺少格点×年份标签。")
        event_weights = np.array([1/groups[r["LAI_exposure_cluster"]] for r in rows])
    observation_weights = event_weights[event_index]
    status["weight_kish"] = float(event_weights.sum()**2/np.sum(event_weights**2))
    beta, fit_status = fit_coefficients(design, y, observation_weights, family)
    status.update(convergence_status=fit_status, separation_flag=fit_status in (
        "possible_separation", "singular_information_possible_separation"))
    if beta is None:
        return
    status["inference_level"] = "point_estimate"
    spatial_ids = {name: i for i, name in enumerate(sorted(set(spatial)))}
    codes = np.array([spatial_ids[name] for name in spatial])
    model_rows = [rows[i] for i in event_index]
    if year_sensitivity is not None:
        from src.M7.scr_year_sensitivity import coefficient_year_sensitivity
        year_sensitivity.extend(coefficient_year_sensitivity(analysis,names,design,y,beta,family,
            [r["year"] for r in model_rows],params,weights=observation_weights))
    covariance = dependence(model_rows, design, y, beta, family, [labels[i] for i in event_index],
                            weights=observation_weights)
    alpha = params["multiple_testing"]["family_alpha"]
    quantiles = params["route1"]["deep_marginal_quantiles"]
    deep = np.quantile(x[:, names.index("deep_SM_pre4_percentile")], quantiles) if analysis.endswith("_I") else []
    marginal_identified = time is None or max(step) == horizon
    use_margins = len(deep) > 0 and marginal_identified
    predicted = margins(names, x, beta, family, time, deep, event_weights) if use_margins else None
    rng = np.random.default_rng(params["random"]["seed"])
    draws, margin_draws = [], []
    repetitions = params["block"]["bootstrap_n"]
    all_covers = {row.get("land_cover") for row in rows}
    failures = Counter()
    for repetition in range(repetitions):
        if report and repetition % 10 == 0:
            report("空间块自举", f"{analysis} · 成功{len(draws)}次 · 失败{sum(failures.values())}次",
                   done=repetition, total=repetitions, unit="次")
        sampled = rng.integers(len(spatial_ids), size=len(spatial_ids))
        weights = np.bincount(sampled, minlength=len(spatial_ids))[codes]
        draw, reason = fit_coefficients(design, y, weights[event_index]*observation_weights, family)
        if draw is not None:
            draws.append(draw)
            if use_margins:
                margin_draws.append(margins(names, x, draw, family, time, deep, event_weights))
        else:
            if reason == "rank_deficient":
                covers = {row.get("land_cover") for row, weight in zip(rows, weights) if weight}
                reason = "missing_land_cover" if len(covers) < len(all_covers) else "rank_deficient"
            failures[reason] += 1
    if report:
        report("空间块自举", f"{analysis} · 成功{len(draws)}次 · 失败{sum(failures.values())}次",
               done=repetitions, total=repetitions, unit="次")
    status["bootstrap_failure_counts"] = json.dumps(dict(sorted(failures.items())))
    status["bootstrap_success"] = len(draws)
    status["bootstrap_requested"] = repetitions
    if len(draws) < repetitions*params["block"]["bootstrap_min_success_fraction"]:
        status["inference_warning"] = "自举成功率不足；保留点估计，正式联合区间和检验不放行"
        draws, margin_draws = [], []
    standard_errors = np.sqrt(np.maximum(0, np.diag(covariance))) if covariance is not None else [None]*width
    formal_intervals = True
    coefficients_for_model = {}
    if test:
        coefficients_for_model[term] = coefficients[-1]
    for i, name in enumerate(names):
        value = float(beta[i])
        se = standard_errors[i]
        if covariance is not None and covariance[i, i] <= 0:
            se = None
        values = [draw[i] for draw in draws]
        boot, clustered, combined = intervals(value, values, se, alpha)
        formal_intervals &= combined[0] is not None
        boot_se = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
        p = max(erfc(abs(value)/(sqrt(2)*error)) for error in (boot_se, se)) if boot_se and se else None
        output = coefficients_for_model.get(name)
        if output is None:
            output = dict(analysis_id=analysis, term=name)
            coefficients.append(output)
        output.update(scale="original" if family in ("median", "mean") else "link", estimate=value,
                      std_error=float(se) if se is not None else None, ci_low=combined[0], ci_high=combined[1],
                      ci_method="union" if combined[0] is not None else None,
                      p_raw=p if name == term and test else None,
                      standardization=(f"mean={scales[name][0]};sd={scales[name][1]}" if name in scales else None))
        uncertainty.extend(interval_rows(analysis, name, "coefficient", boot, clustered, bootstrap_method(params)))
    if (test and coefficients_for_model[term].get("p_raw") is not None and
            (not analysis.endswith("_I") or use_margins)) or (
            not test and formal_intervals):
        status["inference_level"] = "formal"
    if use_margins:
        write_margins(analysis, names, x, beta, family, time, deep, quantiles, scales, covariance,
                      predicted, margin_draws, alpha, marginal, uncertainty, bootstrap_method(params), event_weights)


def interval_rows(analysis, term, quantity, boot, clustered, method="superblock_bootstrap"):
    """展开两种区间及其对应的估计量。"""
    return [dict(analysis_id=analysis, term=term, quantity=quantity, ci_method=method,
                 ci_low=bounds[0], ci_high=bounds[1])
            for method, bounds in ((method, boot), ("block_year", clustered))]


def write_margins(analysis, names, x, beta, family, time, deep, quantiles, scales, covariance,
                  predicted, draws, alpha, marginal, uncertainty, method="superblock_bootstrap", weights=None):
    """输出两个 LAI 水平的概率、差值及两种区间。"""
    gradient = None
    if covariance is not None:
        step = 1e-5
        gradient = np.stack([(margins(names, x, beta+delta, family, time, deep, weights) -
                              margins(names, x, beta-delta, family, time, deep, weights))/(2*step)
                             for delta in np.eye(len(beta))*step], axis=-1)
    mean, sd = scales["deep_SM_pre4_percentile"]
    for i, (level, quantile) in enumerate(zip(deep, quantiles)):
        reference = f"P{quantile*100:g}"
        combined = []
        quantities = (("response_lai_mean", "response_lai_plus_1sd", "response_difference") if family in ("median", "mean") else
                      ("probability_lai_mean", "probability_lai_plus_1sd", "probability_difference"))
        for j, quantity in enumerate(quantities):
            se = None
            if gradient is not None:
                g = gradient[i, j]
                variance = float(g @ covariance @ g)
                if variance > 0:
                    se = sqrt(variance)
            boot, clustered, bounds = intervals(predicted[i, j], [draw[i, j] for draw in draws], se, alpha)
            combined.append(bounds)
            uncertainty.extend(interval_rows(analysis, reference, quantity, boot, clustered, method))
        for j, label in enumerate(("mean", "plus_1sd")):
            low, high = combined[j]
            marginal.append(dict(analysis_id=analysis, term="LAI_trend", deep_reference=reference,
                                 deep_reference_value=float(mean+sd*level), LAI_reference=label,
                                 LAI_reference_value=float(scales["LAI_trend"][0]+j*scales["LAI_trend"][1]),
                                 predicted_probability=float(predicted[i, j]) if family not in ("median", "mean") else None,
                                 predicted_response=float(predicted[i, j]) if family in ("median", "mean") else None,
                                 response_difference=float(predicted[i, 2]) if j and family in ("median", "mean") else None,
                                 probability_difference=float(predicted[i, 2]) if j and family == "logit" else None,
                                 risk_difference=float(predicted[i, 2]) if j and family == "cloglog" else None,
                                 marginal_effect=float(predicted[i, 2]) if j else None,
                                 ci_low=low, ci_high=high, difference_ci_low=combined[2][0] if j else None,
                                 difference_ci_high=combined[2][1] if j else None,
                                 ci_method="union" if low is not None else None,
                                 scale="cumulative_recovery" if family == "cloglog" else
                                       "original_outcome" if family in ("median", "mean") else "probability"))
