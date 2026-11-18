"""单候cloglog截距模型的年份乘子覆盖率诊断，仅写本地验收。
不把简单生成模型的模拟表现推广为完整12候恢复模型或中位数模型的校准。
"""
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
import hashlib
from pathlib import Path
from statistics import NormalDist
import numpy as np
from src.M7.scr_cluster_scores import year_score_draws, multiway_covariance
from workflow.run_module import load_config, DEFAULT_CONFIG
from workflow.freeze_m0 import atomic_write, json_bytes


def wilson(success, total, z):
    """二项覆盖计数的Wilson蒙特卡洛误差区间。"""
    if not total:
        return [None, None]
    p = success/total
    center = (p+z*z/(2*total))/(1+z*z/total)
    half = z*np.sqrt(p*(1-p)/total+z*z/(4*total**2))/(1+z*z/total)
    return [float(center-half), float(center+half)]


def main():
    """固定方案模拟，不按覆盖率寻找更有利的种子或阈值。"""
    params = load_config(DEFAULT_CONFIG)
    cfg = params["infer"]["year_score_calibration"]
    s, t, n = (cfg[k] for k in ("spatial_clusters", "year_clusters", "observations_per_cell"))
    alpha = params["multiple_testing"]["family_alpha"]
    z = NormalDist().inv_cdf(1-alpha/2)
    space, years = np.repeat(np.arange(s),t).tolist(), np.tile(np.arange(t),s).tolist()
    # technical constant：高斯积分节点数，仅用于平滑一维概率期望数值积分。
    nodes, weights = np.polynomial.hermite.hermgauss(80)
    output = dict(config=cfg, params_sha256=hashlib.sha256(DEFAULT_CONFIG.read_bytes()).hexdigest(),
                  seed=params["random"]["seed"], limitation="single_pentad_intercept_only_not_full_model_calibration",
                  results={})
    for label, scenario in cfg["scenarios"].items():
        rng = np.random.default_rng(params["random"]["seed"])
        sd = np.hypot(scenario["space_sd"],scenario["year_sd"])
        truth = float(np.sum(weights*(-np.expm1(-np.exp(cfg["intercept"]+np.sqrt(2)*sd*nodes))))/np.sqrt(np.pi))
        counts = {method:dict(valid=0,covered=0) for method in ("year_score", "two_way", "space_bootstrap", "union")}
        for repeat in range(cfg["replications"]):
            eta = cfg["intercept"]+rng.normal(0,scenario["space_sd"],(s,1))+rng.normal(0,scenario["year_sd"],(1,t))
            cases = rng.binomial(n,-np.expm1(-np.exp(eta)))
            p = cases.sum()/(s*t*n)
            mu = -np.log1p(-p)
            beta = np.array([np.log(mu)])
            scores = ((cases.reshape(-1)-n*p)*mu/p)[:,None]
            info = np.array([[s*t*n*mu*mu*np.exp(-mu)/p]])
            draws, _ = year_score_draws(beta,info,scores,years,params)
            covariance, _ = multiway_covariance(info,scores,space,years)
            intervals = {}
            if draws is not None:
                intervals["year_score"] = np.quantile(-np.expm1(-np.exp(draws[:,0])),[alpha/2,1-alpha/2])
            if covariance is not None and covariance[0,0]>0:
                intervals["two_way"] = -np.expm1(-np.exp(beta[0]+np.array([-1,1])*z*np.sqrt(covariance[0,0])))
            indices = rng.integers(s,size=(params["block"]["bootstrap_n"],s))
            intervals["space_bootstrap"] = np.quantile(cases.sum(axis=1)[indices].sum(axis=1)/(s*t*n),[alpha/2,1-alpha/2])
            if "two_way" in intervals:
                a,b = intervals["two_way"],intervals["space_bootstrap"]
                intervals["union"] = [min(a[0],b[0]),max(a[1],b[1])]
            for method, (lo,hi) in intervals.items():
                counts[method]["valid"] += 1
                counts[method]["covered"] += int(lo<=truth<=hi)
        output["results"][label] = dict(marginal_hazard=truth, methods={method:dict(
            **count, coverage=count["covered"]/count["valid"] if count["valid"] else None,
            mc_wilson_interval=wilson(count["covered"],count["valid"],z)) for method,count in counts.items()})
        print(label,output["results"][label],flush=True)
    atomic_write(Path(__file__).resolve().parents[1]/"metadata/local/year_score_coverage_20261117.json",json_bytes(output))


if __name__ == "__main__":
    main()
