"""十二候恢复曲线覆盖率模拟。使用配置中的空间、年份和交叉情景，逐候输出JSON。"""
import argparse
import json
from collections import Counter
from statistics import NormalDist
import numpy as np
from notebooks.year_score_coverage import wilson
from src.M7.scr_fit_recovery_risk import recovery_time_baseline
from workflow.run_module import DEFAULT_CONFIG, load_config


def simulate(params, repeats):
    """生成具有共享空间及年份效应的整段事件史，经生产曲线接口估计。"""
    cfg = params["infer"]["year_score_calibration"]
    horizon = params["route1"]["recovery_risk_h"]
    nodes, weights = np.polynomial.hermite.hermgauss(80)
    z = NormalDist().inv_cdf(1-params["multiple_testing"]["family_alpha"]/2)
    for scenario, settings in cfg["scenarios"].items():
        rng = np.random.default_rng(params["random"]["seed"])
        s, y = cfg["spatial_clusters"], cfg["year_clusters"]
        blocks = {i:i for i in range(s)}
        sd = np.hypot(settings["space_sd"],settings["year_sd"])
        rate = np.exp(cfg["intercept"] + np.sqrt(2)*sd*nodes)
        survival = np.exp(-np.outer(np.arange(horizon+1),rate)) @ weights / np.sqrt(np.pi)
        truths = {"hazard":1-survival[1:]/survival[:-1],"cumulative":1-survival[1:]}
        valid, hits = Counter(), Counter()
        for _ in range(repeats):
            eta = cfg["intercept"] + rng.normal(0,settings["space_sd"],(s,1)) + rng.normal(0,settings["year_sd"],(1,y))
            end = rng.geometric(-np.expm1(-np.exp(eta))[:,:,None],(s,y,cfg["observations_per_cell"]))
            events, history = [], []
            for (block,year,_person), duration in np.ndenumerate(end):
                eid = len(events)
                events.append(dict(grid_id=block,year=year,episode_id=eid))
                for step in range(1,min(duration,horizon)+1):
                    history.append(dict(episode_id=eid,followup_pentad=step,recovery_event=step==duration,at_risk=True))
            curve,_ = recovery_time_baseline(history,events,blocks,horizon,params["route1"]["recovery_time_df"],
                                            params["infer"],params=params)
            for step,row in enumerate(curve):
                for quantity, truth in truths.items():
                    for method, suffix in (("空间","_ci"),("联合","_union_ci")):
                        low, high = (row.get(quantity+suffix+"_"+side) for side in ("low","high"))
                        key = (step,quantity,method)
                        if low is not None and high is not None:
                            valid[key] += 1
                            hits[key] += int(low <= truth[step] <= high)
        for step in range(horizon):
            for quantity in truths:
                for method in ("空间","联合"):
                    key = (step,quantity,method)
                    n = valid[key]
                    yield dict(scenario=scenario,step=step+1,quantity=quantity,method=method,valid=n,
                               unavailable=repeats-n,coverage=hits[key]/n if n else None,
                               mc_interval=wilson(hits[key],n,z))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repetitions", type=int, help="外层重复次数，默认读取配置")
    args = parser.parse_args()
    params = load_config(DEFAULT_CONFIG)
    repeats = params["infer"]["year_score_calibration"]["replications"] if args.repetitions is None else args.repetitions
    if repeats < 1:
        parser.error("重复次数必须为正数")
    for result in simulate(params,repeats):
        print(json.dumps(result,ensure_ascii=False),flush=True)

