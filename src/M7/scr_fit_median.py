"""以线性规划求解加权中位数回归，并核验原始—对偶最优性。
作者：Codex。版本：v0.1.0。输入：设计矩阵、结局、非负权重。
输出：系数、状态与数值诊断；由 workflow.run_module 的 M7 调用。
"""
import numpy as np
from scipy.optimize import linprog


def fit_weighted_median(x, y, weights):
    """最小化 sum(w*abs(y-Xβ))；不改变样本、模型或抽样权重。"""
    x, y, weights = (np.asarray(a, dtype=float) for a in (x, y, weights))
    if (x.ndim != 2 or y.shape != (len(x),) or weights.shape != y.shape
            or not all(np.isfinite(a).all() for a in (x, y, weights)) or np.any(weights < 0)):
        raise ValueError("中位数回归输入须维度一致、有限且权重非负。")
    keep = weights > 0
    x, y, weights = x[keep], y[keep], weights[keep]
    if not len(y) or np.linalg.matrix_rank(x) < x.shape[1]:
        return None, "rank_deficient", {}
    scale = np.std(y)
    if not scale:
        return None, "constant_outcome", {}
    # technical constants：仅控制浮点可行性与目标差，不是科学推断门槛。
    solver_tolerance, certificate_tolerance = 1e-9, 1e-7
    target = y / scale
    weight_scale = weights.max()
    w = weights / weight_scale
    # 对偶 max target'u，约束 X'u=0、-w<=u<=w；仅p个等式，避免n阶稠密矩阵。
    result = linprog(-target, A_eq=x.T, b_eq=np.zeros(x.shape[1]),
                     bounds=np.column_stack((-w, w)), method="highs-ipm",
                     options={"primal_feasibility_tolerance": solver_tolerance,
                              "dual_feasibility_tolerance": solver_tolerance,
                              "ipm_optimality_tolerance": solver_tolerance})
    if not result.success:
        return None, "lp_nonconverged", {"solver_status": int(result.status)}
    # SciPy的等式marginal是最优目标对右端项的导数，与此处β符号相反。
    beta = -np.asarray(result.eqlin.marginals)
    u = result.x
    primal = float(w @ np.abs(target-x @ beta))
    dual = float(target @ u)
    gap = abs(primal-dual) / max(1., abs(primal), abs(dual))
    feasibility = float(np.max(np.abs(x.T @ u) / np.maximum(1., np.abs(x).T @ w)))
    bounds_error = float(np.max(np.maximum(np.abs(u)-w, 0)))
    diagnostics = {"relative_gap": gap, "relative_feasibility": feasibility,
                   "bounds_error": bounds_error, "objective": primal*scale*weight_scale,
                   "solver_status": int(result.status)}
    if (not np.isfinite(beta).all() or not np.isfinite([gap, feasibility, bounds_error]).all()
            or max(gap, feasibility, bounds_error) > certificate_tolerance):
        return None, "lp_certificate_failed", diagnostics
    return beta*scale, "fitted", diagnostics
