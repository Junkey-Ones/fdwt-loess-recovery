"""Q1条件分布不筛LAI、不混入未恢复事件，也不伪造离散RT联合区间。"""
import numpy as np
from workflow.run_module import DEFAULT_CONFIG,load_config
from src.M7.scr_recovery_distribution import recovery_distribution


def test_distribution_domain_and_discrete_rt():
    p=load_config(DEFAULT_CONFIG)
    p["block"]["bootstrap_n"]=8
    rng=np.random.default_rng(91)
    events=[dict(episode_id=str(i),grid_id=str(i%30),year=2008+i//30,
                 route1_A_eligible=True,RT=2,delta_SMP=float(10+rng.normal()),RR=float(5+rng.normal()))
            for i in range(300)]
    events.append(dict(events[0],episode_id="excluded",route1_A_eligible=False,RT=999))
    exposures=[dict(episode_id=r["episode_id"],land_cover="grassland",exposure_complete_L=False) for r in events]
    rows=recovery_distribution(events,exposures,{str(i):str(i) for i in range(30)}, {},p)
    region=[r for r in rows if r["domain"]=="region"]
    assert len(region)==5 and all(r["n_event"]==300 for r in region)
    rt=next(r for r in region if r["metric"]=="RT")
    assert rt["estimate"]==2 and rt["bootstrap_ci_low"]==rt["bootstrap_ci_high"]==2
    assert rt["ci_low"] is None and rt["limitation"]=="upper_unbounded"
    delta=next(r for r in region if r["metric"]=="delta_SMP" and r["statistic"]=="mean")
    assert delta["estimate"]==np.mean([r["delta_SMP"] for r in events[:-1]])
