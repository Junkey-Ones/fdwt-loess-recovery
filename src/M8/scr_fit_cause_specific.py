"""脚本名：scr_fit_cause_specific.py（M8 · 原因别时间基线）
功能简介：拟合 A、B 离散时间 logistic 原因别风险及模型累计发生率。
作者：Codex
版本：v0.1.0
读取数据：M8 当候风险集和样本门槛。
生成数据：原因别时间基线及拟合状态。
其他文件：统一入口写入回执和日志。
运行示例：python -m workflow.run_module M8 --run-alias 2026-11-11_主分析
退出码：由统一入口定义。
"""
import numpy as np

from src.M7.scr_fit_recovery_risk import natural_spline


def fit_logistic(design, sizes, counts):
    """以稳定二项对数似然拟合，明确报告分离或秩不足。"""
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return None, "rank_deficient"
    beta = np.zeros(design.shape[1])
    beta[0] = np.log(counts.sum() / (sizes.sum() - counts.sum()))

    def likelihood(eta):
        return float(np.sum(-counts * np.logaddexp(0, -eta) - (sizes - counts) * np.logaddexp(0, eta)))

    for _ in range(100):
        eta = design @ beta
        probability = np.exp(-np.logaddexp(0, -eta))
        weight = sizes * probability * (1 - probability)
        information = design.T @ (design * weight[:, None])
        if np.linalg.matrix_rank(information) < design.shape[1]:
            return None, "rank_deficient"
        score = design.T @ (counts - sizes * probability)
        change = np.linalg.solve(information, score)
        baseline = likelihood(eta)
        for power in range(21):
            step = change / (2 ** power)
            candidate = design @ (beta + step)
            if likelihood(candidate) >= baseline - 1e-10:
                if np.max(np.abs(candidate)) > 25:
                    return None, "possible_separation"
                beta += step
                break
        else:
            return None, "nonconverged"
        if np.max(np.abs(step)) < 1e-8 and np.max(np.abs(score)) < 1e-6:
            return beta, "point_estimate"
    return None, "nonconverged"


def fit_cause_specific(curve, horizon, df, epv_min):
    """拟合两个出口的时间基线并检查风险是否形成有效分布。"""
    if df != 3 or horizon < 4:
        raise ValueError("路线二时间基线要求三个样条自由度及至少四候。")
    observed = [row for row in curve if row["n_at_risk"]]
    sizes = np.array([row["n_at_risk"] for row in observed], dtype=float)
    times = [row["followup_pentad"] for row in observed]
    design = natural_spline(times, horizon)
    estimates, diagnostics = [], {}
    for cause, field in (("A", "n_exit_a"), ("B", "n_exit_b")):
        counts = np.array([row[field] for row in observed], dtype=float)
        n_exit = int(counts.sum())
        epv = n_exit / (df + 1)
        if epv < epv_min or n_exit == sizes.sum():
            beta, status = None, "insufficient_support"
        else:
            beta, status = fit_logistic(design, sizes, counts)
        diagnostics[cause] = dict(status=status, n_exit=n_exit, epv=epv,
                                  coefficients=beta.tolist() if beta is not None else None)
        if beta is not None:
            estimates.append(np.exp(-np.logaddexp(0, -(design @ beta))))
    if len(estimates) != 2:
        return [], dict(status="model_unavailable", causes=diagnostics)
    if np.any(estimates[0] + estimates[1] > 1):
        return [], dict(status="incompatible_hazards", causes=diagnostics)
    survival, cif_a, cif_b = 1.0, 0.0, 0.0
    result = []
    for step, a, b in zip(times, *estimates):
        if step != len(result) + 1:
            break
        cif_a += survival * a
        cif_b += survival * b
        survival *= 1 - a - b
        result.append(dict(followup_pentad=step, hazard_a=float(a), hazard_b=float(b),
                           cif_a=float(cif_a), cif_b=float(cif_b), survival=float(survival),
                           probability_c=float(survival) if step == horizon else None))
    median = next((row["followup_pentad"] for row in result if row["survival"] <= 0.5), None)
    return result, dict(status="point_estimate", causes=diagnostics, median_exit_pentad=median)
