"""脚本名：scr_fit_recovery_risk.py（M7 · 恢复风险时间基线）
功能简介：拟合离散时间 cloglog 恢复风险与累计恢复概率。
作者：Codex
版本：v0.1.0
读取数据：M7 事件—候风险表、M5 事件与 M2 空间块。
生成数据：按候风险表及拟合诊断。
其他文件：统一入口写入回执和日志。
运行示例：python -m workflow.run_module M7 --run-alias 2026-11-11_主分析
退出码：由统一入口定义。
"""
from collections import Counter

import numpy as np
from src.M7.scr_spatial_inference import bootstrap_method, resampling_label


def natural_spline(times, horizon):
    """以随访区间的端点及两个等距内结点形成三自由度时间基线。"""
    x = (np.asarray(times, dtype=float) - 1) / (horizon - 1)
    right = np.maximum(x - 1, 0) ** 3

    def truncated_cubic(knot):
        return (np.maximum(x - knot, 0) ** 3 - right) / (1 - knot)

    reference = truncated_cubic(2 / 3)
    return np.column_stack((np.ones_like(x), x, truncated_cubic(0) - reference,
                            truncated_cubic(1 / 3) - reference))


def fit_grouped_cloglog(design, sizes, counts):
    """用分组二项对数似然和 Fisher scoring 拟合，报告可辨识性。"""
    total = counts.sum()
    trials = sizes.sum()
    if total <= 0 or total >= trials:
        return None, "no_outcome_variation"
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return None, "rank_deficient"
    beta = np.zeros(design.shape[1])
    beta[0] = np.log(-np.log1p(-total / trials))

    def evaluate(coefficients):
        eta = design @ coefficients
        if not np.isfinite(eta).all() or np.any(abs(eta) > 25):
            return None
        mu = np.exp(eta)
        p = -np.expm1(-mu)
        log_likelihood = float(np.sum(counts * np.log(p) - (sizes - counts) * mu))
        return mu, p, log_likelihood

    for _ in range(100):
        mu, p, likelihood = evaluate(beta)
        weight = sizes * mu ** 2 * np.exp(-mu) / p
        score = design.T @ ((counts - sizes * p) * mu / p)
        information = design.T @ (design * weight[:, None])
        if np.linalg.matrix_rank(information) < design.shape[1]:
            return None, "singular_information"
        direction = np.linalg.solve(information, score)
        for power in range(21):
            change = direction / (2 ** power)
            candidate = evaluate(beta + change)
            if candidate is not None and candidate[2] >= likelihood - 1e-10:
                beta += change
                break
        else:
            return None, "nonconverged"
        if np.max(np.abs(change)) < 1e-8 and np.max(np.abs(score)) < 1e-6:
            return beta, "point_estimate"
    return None, "nonconverged"


def recovery_time_baseline(risk, events, blocks, horizon, time_df, settings, *, params=None,
                           superblocks=None, report=None):
    """按事件数、空间块和 EPV 门槛拟合时间基线，保留无支撑候。"""
    sizes, counts = Counter(), Counter()
    recovered, enrolled, entered = set(), set(), set()
    for row in risk:
        enrolled.add(row["episode_id"])
        if row["at_risk"]:
            entered.add(row["episode_id"])
            step = row["followup_pentad"]
            sizes[step] += 1
            if row["recovery_event"]:
                counts[step] += 1
                recovered.add(row["episode_id"])
    n, positives = len(entered), len(recovered)
    observed_blocks = {blocks.get(event["grid_id"]) for event in events
                       if event["episode_id"] in entered} - {None}
    dimensions = time_df + 1
    support = dict(n_enrolled=len(enrolled), n_event=n, n_recovered=positives, n_nonrecovered=n-positives,
                   n_blocks=len(observed_blocks), epv=positives / dimensions)
    status, coefficients = "insufficient_support", None
    times = sorted(sizes)
    if (n >= settings["min_n"] and min(positives, n-positives) >= settings["min_event_per_arm"]
            and len(observed_blocks) >= settings["min_blocks"] and support["epv"] >= settings["epv_min"]):
        if time_df != 3 or horizon < 4:
            raise ValueError("恢复风险时间基线要求三个样条自由度及至少四候。")
        coefficients, status = fit_grouped_cloglog(
            natural_spline(times, horizon), np.array([sizes[t] for t in times], dtype=float),
            np.array([counts[t] for t in times], dtype=float))
    hazards = {}
    if coefficients is not None:
        hazards = dict(zip(times, map(float, -np.expm1(-np.exp(natural_spline(times, horizon) @ coefficients)))))
    survival, output = 1.0, []
    for step in range(1, horizon + 1):
        hazard = hazards.get(step)
        survival = survival * (1 - hazard) if hazard is not None and survival is not None else None
        output.append(dict(followup_pentad=step, n_at_risk=sizes[step], n_recovery=counts[step],
                           hazard=hazard, cumulative_recovery=1 - survival if survival is not None else None,
                           status=status))
    support.update(status=status, coefficients=coefficients.tolist() if coefficients is not None else None)
    curve_intervals(output, support, risk, events, blocks, horizon, params, superblocks or {}, report)
    if params is not None:
        from src.M7.scr_q1_dependence import add_curve_dependence
        add_curve_dependence(output,support,risk,events,blocks,natural_spline(range(1,horizon+1),horizon),params)
    return output, support


def curve_intervals(output, support, risk, events, blocks, horizon, params, superblocks, report):
    """按空间块充分统计量重抽完整历史，写逐候点位区间；无支撑候不外推。"""
    for row in output:
        row.update(hazard_ci_low=None, hazard_ci_high=None, cumulative_ci_low=None, cumulative_ci_high=None,
                   bootstrap_success_hazard=0, bootstrap_success_cumulative=0, bootstrap_requested=0,
                   n_resampling_block=0, ci_method=None, ci_level=None, ci_scope="pointwise",
                   interval_status="not_requested")
    if params is None:
        return
    repeats = params["block"]["bootstrap_n"]
    minimum = repeats * params["block"]["bootstrap_min_success_fraction"]
    alpha = params["multiple_testing"]["family_alpha"]
    if repeats < 2 or not 0 < alpha < 1:
        raise ValueError("恢复曲线自举次数须至少2次，alpha须在0与1之间。")
    event_blocks = {e["episode_id"]: blocks.get(e["grid_id"]) for e in events}
    totals, recoveries, members = {}, {}, {}
    for row in risk:
        if not row["at_risk"]:
            continue
        block = event_blocks.get(row["episode_id"])
        if block is None:
            raise ValueError("恢复风险事件缺少空间块，不能静默丢弃后计算区间。")
        label = resampling_label(block, superblocks, params)
        if label not in totals:
            totals[label], recoveries[label], members[label] = np.zeros(horizon), np.zeros(horizon), set()
        step = row["followup_pentad"]-1
        if not 0 <= step < horizon:
            raise ValueError("风险表候序号超出所选随访期。")
        totals[label][step] += 1
        recoveries[label][step] += int(row["recovery_event"])
        members[label].add(row["episode_id"])
    keys = sorted(totals)
    sizes = np.array([len(members[k]) for k in keys], dtype=float)
    effective = float(sizes.sum()**2/(sizes @ sizes)) if len(sizes) else 0.
    support.update(n_resampling_block=len(keys), n_eff=effective, bootstrap_requested=repeats,
                   bootstrap_success=0, bootstrap_failure_counts={}, ci_method=bootstrap_method(params),
                   ci_scope="pointwise", ci_level=1-alpha, interval_status="insufficient_support")
    for row in output:
        row.update(bootstrap_requested=repeats, n_resampling_block=len(keys), ci_method=bootstrap_method(params),
                   ci_level=1-alpha, interval_status="insufficient_support")
    if (support["coefficients"] is None or len(keys) < params["infer"]["min_blocks"]
            or effective < params["infer"]["min_n_eff"]):
        return
    totals, recoveries = np.stack([totals[k] for k in keys]), np.stack([recoveries[k] for k in keys])
    design = natural_spline(range(1, horizon+1), horizon)
    hazard_draws = [[] for _ in range(horizon)]
    cumulative_draws = [[] for _ in range(horizon)]
    rng = np.random.default_rng(params["random"]["seed"])
    failures, successes = Counter(), 0
    for iteration in range(repeats):
        sampled = rng.integers(len(keys), size=len(keys))
        n, d = totals[sampled].sum(axis=0), recoveries[sampled].sum(axis=0)
        valid = n > 0
        beta, status = fit_grouped_cloglog(design[valid], n[valid], d[valid])
        if beta is None:
            failures[status] += 1
        else:
            successes += 1
            hazards = np.full(horizon, np.nan)
            hazards[valid] = -np.expm1(-np.exp(design[valid] @ beta))
            survival = 1.
            for j in range(horizon):
                if valid[j]:
                    hazard_draws[j].append(float(hazards[j]))
                survival = survival*(1-hazards[j]) if valid[j] and survival is not None else None
                if survival is not None:
                    cumulative_draws[j].append(float(1-survival))
        if report and ((iteration+1) % 10 == 0 or iteration+1 == repeats):
            report("Q1恢复曲线空间自举", f"H={horizon} · 成功{successes}次 · 失败{sum(failures.values())}次",
                   done=iteration+1, total=repeats, unit="次")
    for j, row in enumerate(output):
        row.update(bootstrap_success_hazard=len(hazard_draws[j]),
                   bootstrap_success_cumulative=len(cumulative_draws[j]))
        for value, draws, low, high in (
                (row["hazard"], hazard_draws[j], "hazard_ci_low", "hazard_ci_high"),
                (row["cumulative_recovery"], cumulative_draws[j], "cumulative_ci_low", "cumulative_ci_high")):
            if value is not None and len(draws) >= minimum:
                row[low], row[high] = map(float, np.quantile(draws, [alpha/2, 1-alpha/2]))
        row["interval_status"] = ("available" if row["hazard_ci_low"] is not None and row["cumulative_ci_low"] is not None
                                  else "no_risk_support" if row["hazard"] is None else "insufficient_bootstrap")
    support.update(bootstrap_success=successes, bootstrap_failure_counts=dict(failures),
                   interval_status="available" if all(r["interval_status"] == "available" for r in output) else "partial_or_unavailable")
