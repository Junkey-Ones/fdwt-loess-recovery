"""聚类得分三项分解与年份乘子的独立手算核对。"""
import numpy as np
from copy import deepcopy
from workflow.run_module import load_config, DEFAULT_CONFIG
from src.M7.scr_cluster_scores import grouped_scores,multiway_covariance,year_score_draws
from src.M7.scr_year_sensitivity import coefficient_year_sensitivity


def test_multiway_matches_manual_three_term_sum():
    """用手工簇求和核对空间+年份-交叉以及小样本因子。"""
    rng=np.random.default_rng(51)
    space=np.repeat(np.arange(15),12).tolist()
    years=np.tile(np.arange(12),15).tolist()
    scores=rng.normal(size=(15,2))[space]+rng.normal(size=(12,2))[years]
    information=np.array([[100.,4.],[4.,90.]])
    covariance,audit=multiway_covariance(information,scores,space,years)
    terms=[]
    for labels in (space,years,list(zip(space,years))):
        distinct=set(labels)
        grouped=np.array([sum((scores[i] for i,label in enumerate(labels) if label==key),np.zeros(2)) for key in distinct])
        terms.append(grouped.T @ grouped*len(distinct)/(len(distinct)-1))
    inv=np.linalg.inv(information)
    expected=inv @ (terms[0]+terms[1]-terms[2]) @ inv
    assert audit["status"]=="available"
    np.testing.assert_allclose(covariance,expected,rtol=1e-12,atol=1e-12)


def test_year_draws_match_frozen_signs_and_reject_few_years():
    """核对随机符号、中心化和线性映射，不把少簇输入放行。"""
    p=deepcopy(load_config(DEFAULT_CONFIG))
    scores=np.arange(40,dtype=float).reshape(20,2)/20
    years=list(range(2000,2020));information=np.diag([4.,5.]);beta=np.array([.2,-.3])
    draws,audit=year_score_draws(beta,information,scores,years,p)
    signs=2*np.random.default_rng(p["random"]["seed"]).integers(0,2,size=(500,20))-1
    expected=beta+signs @ (scores-scores.mean(axis=0))*np.sqrt(20/19) @ np.linalg.inv(information).T
    np.testing.assert_array_equal(draws,expected)
    assert audit["method"]=="year_wild_score_linearized"
    assert year_score_draws(beta,information,scores,[2000]*20,p)[0] is None


def test_mean_year_sensitivity_uses_original_units():
    """均值模型扰动以原量纲发布，且不生成主检验p值。"""
    p=load_config(DEFAULT_CONFIG)
    x=np.column_stack((np.ones(100),np.arange(100)/100))
    y=3+2*x[:,1]+np.sin(np.arange(100))
    beta=np.linalg.lstsq(x,y,rcond=None)[0]
    rows=coefficient_year_sensitivity("mean",["intercept","x"],x,y,beta,"mean",[2000+i//5 for i in range(100)],p)
    assert all(r["status"]=="available" and r["bootstrap_success"]==500 for r in rows)
    assert rows[1]["estimate"]==beta[1] and "p_raw" not in rows[1]
