"""脚本名：scr_model_sensitivity.py（M7单因素模型敏感性）。
作者：Codex。输入：冻结事件、暴露、各随访风险表；输出：独立敏感性表。
通过workflow.run_module调用，共用主模型拟合器，不修改原始输入或主检验。
"""
from copy import deepcopy
from src.M7.scr_fit_route1_models import fit_route1_models


TABLES = {
    "model_fit_manifest": "sensitivity_model_manifest",
    "model_result": "sensitivity_model_result",
    "model_marginal": "sensitivity_model_marginal",
    "route1_model_uncertainty": "sensitivity_model_uncertainty",
    "route1_year_wild_sensitivity": "sensitivity_year_wild",
}


def fit_sensitivity(version, events, exposures, risk, blocks, superblocks, params, identity,
                    horizon=None, report=None):
    """只改变登记的一个因素；敏感性检验不混入原Holm家族。"""
    configured = params["route1"]["model_sensitivities"]
    if version not in configured:
        raise ValueError(f"M7未登记模型敏感性：{version}")
    local = deepcopy(params)
    sample_mode = "event"
    if version == "q2_mean":
        selection = "q2_mean"
    elif version == "q3_continuous":
        selection = "q3_continuous"
    elif version == "nonforest":
        selection = "q3"
        eligible = {r["episode_id"] for r in exposures if r.get("land_cover") not in (None, "forest")}
        events = [r for r in events if r["episode_id"] in eligible]
    elif version == "common_sample":
        selection, sample_mode = "q3", version
    elif version in ("one_per_exposure", "inverse_exposure"):
        selection, sample_mode = "q3_lai", version
    elif version == "year_factor":
        selection = None
        local["covariates"]["core"] = [key for key in local["covariates"]["core"] if key != "year_centered_2000"]+["year_factor"]
    elif version == "reduced_soil_terrain":
        selection = None
        local["covariates"]["core"] = [key for key in local["covariates"]["core"]
                                       if key not in params["sensitivity"]["reduced_soil_terrain_drop"]]
    elif version in params["sensitivity"]["block_km"]:
        selection = None
        local["block"]["km"] = params["sensitivity"]["block_km"][version]
        if local["block"]["resampling_unit"] != "fixed_space":
            raise ValueError("空间尺度敏感性仅适用于已登记的固定块修订。")
    elif version in (*params["sensitivity"]["followup"], *params["route1"]["q1_censor_sensitivities"]):
        if horizon is None:
            raise ValueError("随访敏感性必须提供对应风险表及随访上限。")
        selection = "q3_recovery"
        local["route1"]["recovery_risk_h"] = horizon
    else:
        raise ValueError(f"模型敏感性尚未实现：{version}")
    output = fit_route1_models(events, exposures, risk, blocks, superblocks, local, identity,
                              report=report, selection=selection, exploratory=True, sample_mode=sample_mode)
    if version in params["sensitivity"]["block_km"]:
        for row in output["model_fit_manifest"]:
            row["n_superblock"] = None
    return {target: [dict(row, sensitivity=version) for row in output[source]]
            for source, target in TABLES.items()}
