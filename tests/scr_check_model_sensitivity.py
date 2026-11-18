"""M7敏感性独立核验：加权拟合、抽样稳定性及主检验隔离。"""
from copy import deepcopy
import numpy as np
from workflow.run_module import DEFAULT_CONFIG, load_config
from src.M7.scr_fit_route1_models import fit_coefficients, fit_one_model, dependence
from src.M7.scr_model_sensitivity import fit_sensitivity


def test_weighted_mean_matches_replicated_rows():
    """整数权重与实际复制观测的OLS完全对应。"""
    x = np.column_stack((np.ones(7), np.arange(7)))
    y = np.array([2., 1., 5., 3., 8., 5., 11.])
    w = np.array([2, 3, 1, 0, 1, 4, 2])
    beta, status = fit_coefficients(x, y, w, "mean")
    expected = np.linalg.lstsq(np.repeat(x, w, axis=0), np.repeat(y, w), rcond=None)[0]
    np.testing.assert_allclose(beta, expected)
    assert status == "fitted"


def test_year_factor_has_reference_without_numeric_standardization():
    """年份分类仅有K-1个哑变量，不能同时保留线性年份项。"""
    from src.M7.scr_fit_route1_models import design_matrix
    rows = [dict(year_factor=y) for y in (2010,2011,2012,2010)]
    names, matrix, scales = design_matrix(rows, [], ["year_factor"])
    assert names == ["intercept", "year_factor[2011]", "year_factor[2012]"]
    np.testing.assert_array_equal(matrix,[[1,0,0],[1,1,0],[1,0,1],[1,0,0]])
    assert not scales


def test_design_rank_failure_is_not_separation():
    """重复列与完全分离明确区分，不能把两者都建议用Firth修复。"""
    x = np.column_stack((np.ones(40), np.repeat([-1.,1.],20)))
    y = np.repeat([0.,1.],20)
    beta, status = fit_coefficients(x,y,np.ones(40),"logit")
    assert beta is None and status in ("possible_separation", "singular_information_possible_separation")
    beta, status = fit_coefficients(np.column_stack((x,x[:,1])),y,np.ones(40),"logit")
    assert beta is None and status == "rank_deficient"


def model_sample():
    """大小不等的共享暴露簇，深层与LAI非共线。"""
    rng = np.random.default_rng(17)
    rows = []
    for b in range(30):
        for year in range(2008, 2024):
            lai, base = rng.normal(size=2)
            for j in range(1+b % 3):
                rows.append(dict(episode_id=f"{b}:{year}:{j}", grid_id=str(b), year=year,
                    LAI_trend=lai, LAI_base=base, LAI_exposure_cluster=f"{b}:{year}",
                    F_R=bool(rng.integers(2)), deep_SM_pre4_percentile=float(rng.normal()),
                    product="test", definition_id="main", support_id="own", route1_FR_eligible=True,
                    exposure_complete_L=True, exposure_complete_D=True, exposure_complete_I=True))
    return rows


def test_cluster_sample_independent_of_input_order_and_weighted_logit():
    """每簇一次抽样对输入排列不敏感；加权点估计满足加权得分方程。"""
    p = load_config(DEFAULT_CONFIG)
    p["block"]["bootstrap_n"] = 4
    rows = model_sample()
    original = deepcopy(rows)
    blocks = {str(b): str(b) for b in range(30)}
    results = []
    for mode, candidates in (("one_per_exposure", rows), ("one_per_exposure", rows[::-1]),
                              ("inverse_exposure", rows)):
        manifest, coef = [], []
        spec = ("q3_fr_L", "Q3", "logit", "F_R", ["LAI_trend", "LAI_base"], candidates, None)
        fit_one_model(spec, {}, [], blocks, {}, p, {}, manifest, coef, [], [], sample_mode=mode)
        results.append((manifest, coef))
    assert results[0] == results[1]
    assert results[0][0][0]["n_event"] == 480
    assert rows == original
    from src.M7.scr_fit_route1_models import design_matrix, logistic
    from collections import Counter
    names, x, _ = design_matrix(rows, ["LAI_trend", "LAI_base"], [])
    beta = np.array([next(c["estimate"] for c in results[2][1] if c["term"] == name) for name in names])
    sizes = Counter(r["LAI_exposure_cluster"] for r in rows)
    w = np.array([1/sizes[r["LAI_exposure_cluster"]] for r in rows])
    y = np.array([r["F_R"] for r in rows])
    np.testing.assert_allclose(x.T @ (w*(y-logistic(x @ beta))), 0., atol=1e-6)


def test_mean_sensitivity_excludes_post_and_has_no_primary_tests():
    """均值与中位数采用同一对比样本，独立输出且不生成主p值。"""
    p = load_config(DEFAULT_CONFIG)
    p["covariates"]["core"] = []
    p["block"]["bootstrap_n"] = 4
    rows = model_sample()
    for i, row in enumerate(rows):
        row.update(F_R_subtype="post" if row["F_R"] and i % 4 == 0 else "pre",
                   RR=2*row["F_R"]+np.sin(i), delta_SMP=3*row["F_R"]+np.cos(i))
    result = fit_sensitivity("q2_mean", rows, rows, [], {str(b): str(b) for b in range(30)}, {}, p, {})
    manifest = result["sensitivity_model_manifest"]
    assert len(manifest) == 2
    expected = sum(not r["F_R"] or r["F_R_subtype"] != "post" for r in rows)
    assert all(r["n_event"] == expected and r["link_function"] == "identity" for r in manifest)
    assert all(r.get("p_raw") is None and r.get("test_id") is None and r["scale"] == "original"
               for r in result["sensitivity_model_result"])


def test_covariate_sensitivities_change_only_registered_terms():
    """实际拟合器核对年份替换和土壤精简，输入及主配置不能被改写。"""
    p = load_config(DEFAULT_CONFIG)
    p["block"]["bootstrap_n"] = 3
    p["covariates"]["core"] = ["year_centered_2000", "sand_0_30", "clay_0_30", "elevation_m", "slope_deg"]
    original = deepcopy(p)
    rows = model_sample()
    rng = np.random.default_rng(771)
    for row in rows:
        row.update(year_centered_2000=row["year"]-2000, F_R_subtype="pre",
                   RR=float(rng.normal()), delta_SMP=float(rng.normal()))
        row.update(zip(("sand_0_30", "clay_0_30", "elevation_m", "slope_deg"),rng.normal(size=4)))
    blocks = {str(b): str(b) for b in range(30)}
    for version in ("year_factor", "reduced_soil_terrain"):
        result = fit_sensitivity(version, rows, rows, [], blocks, {}, p, {})
        formulas = [r["formula"] for r in result["sensitivity_model_manifest"] if r.get("formula")]
        assert formulas
        if version == "year_factor":
            assert all("year_factor[" in f and "year_centered_2000" not in f for f in formulas)
        else:
            assert all("sand_0_30" not in f and "slope_deg" not in f and "clay_0_30" in f and "elevation_m" in f for f in formulas)
    assert p == original


def test_secondary_continuous_keeps_post_and_unknown_without_binary_arms():
    """次级连续模型不沿用H1对照筛选，预测必须是原量纲而非概率。"""
    p=load_config(DEFAULT_CONFIG);p["covariates"]["core"]=[];p["block"]["bootstrap_n"]=3
    rows=model_sample();rng=np.random.default_rng(505)
    for i,r in enumerate(rows):
        r.update(route1_A_eligible=True,F_R_subtype="post",F_R=None if i%5==0 else True,
                 RR=10+r["LAI_trend"]+.3*r["LAI_trend"]*r["deep_SM_pre4_percentile"]+rng.normal(),
                 delta_SMP=20+2*r["LAI_trend"]+rng.normal())
    result=fit_sensitivity("q3_continuous",rows,rows,[],{str(b):str(b) for b in range(30)}, {},p,{})
    manifests=result["sensitivity_model_manifest"]
    assert len(manifests)==6 and all(r["n_event"]==len(rows) for r in manifests)
    assert all(r["n_outcome"] is None and r["n_nonoutcome"] is None for r in manifests)
    margins=result["sensitivity_model_marginal"]
    assert len(margins)==12 and all(r["predicted_probability"] is None for r in margins)
    assert all(r["predicted_response"]>1 and r["scale"]=="original_outcome" for r in margins)
    assert all(r.get("test_id") is None for r in result["sensitivity_model_result"])
