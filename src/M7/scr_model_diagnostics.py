"""M7主模型的非线性适用性、等价与最小可检测效应诊断。
作者：Codex。输入模型清单/系数/params，输出独立诊断表；不修改主检验。
统一入口运行；区间宽度近似MDE不是事后观察功效或有限样本保证。
"""
from math import log, isfinite
from statistics import NormalDist


def model_diagnostics(manifests, coefficients, params):
    """只按冻结界限解释已有区间，缺少区间不得称等价。"""
    output = []
    normal = NormalDist()
    alpha = params["multiple_testing"]["family_alpha"]
    z = normal.inv_cdf(1-alpha/2)
    for manifest in manifests:
        model = manifest["analysis_id"]
        effective = manifest.get("n_eff", 0)
        gam = ("retain_linear_insufficient_support" if effective < params["gam"]["min_reference_n_eff"] else
               "reference_only" if effective < params["gam"]["min_fit_n_eff"] else "requires_shape_analysis")
        if manifest.get("question") == "Q2":
            gam = "not_applicable_no_lai_exposure"
        for row in coefficients:
            if row["analysis_id"] != model or not row.get("test_id"):
                continue
            lower = upper = None
            family = manifest["model_family"]
            if family == "logit":
                lower, upper = map(log,params["equivalence"]["or"])
            elif family == "median" and manifest.get("outcome_sd"):
                upper = params["equivalence"]["cont_sd"]*manifest["outcome_sd"]
                lower = -upper
            estimate, low, high = (row.get(k) for k in ("estimate", "ci_low", "ci_high"))
            available = all(v is not None and isfinite(v) for v in (estimate,low,high))
            equivalent = available and lower is not None and low >= lower and high <= upper
            status = ("interval_unavailable" if not available else "no_prespecified_bound" if lower is None
                      else "within_equivalence_bounds" if equivalent else "equivalence_not_demonstrated")
            mde = None
            if available:
                count = len(params["multiple_testing"]["families"][row["test_family"]])
                width_se = max(estimate-low,high-estimate)/z
                mde = width_se*(normal.inv_cdf(1-alpha/(2*count))+normal.inv_cdf(params["infer"]["target_power"]))
            output.append(dict(analysis_id=model,term=row["term"],test_id=row["test_id"],gam_status=gam,
                n_eff=effective,equivalence_low=lower,equivalence_high=upper,equivalence_status=status,
                mde=mde,mde_scale=row["scale"],target_power=params["infer"]["target_power"],
                mde_method="normal_interval_width_bonferroni_approximation" if mde is not None else None,
                interpretation="small_effect_within_bounds" if equivalent else
                    "detected_association" if row.get("p_holm") is not None and row["p_holm"]<alpha else
                    "insufficient_evidence"))
    return output
