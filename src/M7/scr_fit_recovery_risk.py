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
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return None, "rank_deficient"
    beta = np.zeros(design.shape[1])
    beta[0] = np.log(-np.log1p(-counts.sum() / sizes.sum()))

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
            return None, "rank_deficient"
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


def recovery_time_baseline(risk, events, blocks, horizon, time_df, settings):
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
    return output, support
