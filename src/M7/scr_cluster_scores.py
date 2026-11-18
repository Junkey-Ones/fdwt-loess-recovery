"""空间×年份聚类协方差及年份簇得分乘子敏感性。
作者：Codex。输入：逐观测得分、信息矩阵与簇标签；输出：协方差/系数扰动。
仅由M7统一调度调用，年份乘子法不冒充有限样本精确校准。
"""
from collections import defaultdict
import numpy as np


def grouped_scores(scores, labels):
    """按同一簇累计得分，保持完整事件历史的共有标签。"""
    groups = defaultdict(lambda: np.zeros(scores.shape[1]))
    for label, score in zip(labels, scores, strict=True):
        groups[label] += score
    return np.stack([groups[k] for k in sorted(groups)]) if groups else np.empty((0,scores.shape[1]))


def multiway_covariance(information, scores, space, years):
    """V_space+V_year-V_intersection；不静默截断负特征值。"""
    information, scores = np.asarray(information), np.asarray(scores)
    if np.linalg.matrix_rank(information) < information.shape[0]:
        return None, {"status":"singular_information"}
    meats, counts = [], []
    for labels in (space, years, list(zip(space,years))):
        grouped = grouped_scores(scores,labels)
        g = len(grouped)
        counts.append(g)
        if g < 2:
            return None, {"status":"insufficient_clusters"}
        meats.append(grouped.T @ grouped*g/(g-1))
    inverse = np.linalg.inv(information)
    cov = inverse @ (meats[0]+meats[1]-meats[2]) @ inverse
    cov = (cov+cov.T)/2
    eig = np.linalg.eigvalsh(cov)
    # technical constant：浮点舍入容差，不把实质负方差修成正数。
    tolerance = 1e-10*max(1.,float(np.max(np.abs(eig))))
    diagnostic = dict(status="available" if eig.min() >= -tolerance else "non_psd",
                      n_space=counts[0],n_year=counts[1],n_intersection=counts[2],minimum_eigenvalue=float(eig.min()))
    return (cov if diagnostic["status"]=="available" else None), diagnostic


def year_score_draws(beta, information, scores, years, params):
    """年份簇中心化得分的Rademacher一次线性化扰动，仅作敏感性。"""
    grouped = grouped_scores(scores,years)
    g = len(grouped)
    settings = params["infer"]["year_score_bootstrap"]
    if settings["weights"] != "rademacher":
        raise ValueError("年份得分bootstrap只实现已登记的Rademacher权重。")
    if g < settings["min_clusters"] or np.linalg.matrix_rank(information)<len(beta):
        return None,dict(status="insufficient_support",n_year=g,method="year_wild_score_linearized")
    rng = np.random.default_rng(params["random"]["seed"])
    multipliers = 2*rng.integers(0,2,size=(settings["repetitions"],g))-1
    centered = grouped-grouped.mean(axis=0)
    draws = beta+(multipliers @ centered)*np.sqrt(g/(g-1)) @ np.linalg.inv(information).T
    return draws,dict(status="available",n_year=g,bootstrap_requested=settings["repetitions"],
                      method="year_wild_score_linearized",calibration="asymptotic_sensitivity_not_exact")
