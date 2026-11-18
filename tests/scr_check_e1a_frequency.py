"""E1a零年分母与NB2频率压缩的独立数值核验。"""
import numpy as np
import pyarrow as pa
from scipy.optimize import minimize
from scipy.stats import nbinom
from workflow.run_module import DEFAULT_CONFIG,load_config
from src.M7.scr_e1a_frequency import count_grid_years,fit_nb2


def test_zero_years_and_unknown_windows_are_not_conflated():
    p=load_config(DEFAULT_CONFIG);p["time"].update(year_start=2019,year_end=2020)
    masks=[dict(grid_id=g,mask_include=True) for g in ("a","b")]
    series=[dict(grid_id=g,year=y,active_window_length_L=2,active_flag=True,
                 smp=30.,p_mm=1.,p95_usable=True) for g in ("a","b") for y in (2019,2020) for _ in range(2)]
    events=[dict(grid_id="b",year=2020,route1_FR_eligible=True,F_R=None,t_e=10)]
    rows=count_grid_years([pa.RecordBatch.from_pylist(series)],masks,events,{"a":"1","b":"2"},p)
    assert len(rows)==4 and sum(r["included"] for r in rows)==3
    assert all(r["rate"]==0 for r in rows if r["included"])
    unknown=next(r for r in rows if not r["included"])
    assert unknown["exclusion_reason"]=="unknown_fr_window" and unknown["rate"] is None


def test_nb2_matches_independent_distribution_likelihood_and_frequency_expansion():
    p=load_config(DEFAULT_CONFIG);rng=np.random.default_rng(833)
    x=np.column_stack((np.ones(500),rng.normal(size=500)))
    offset=np.log(rng.integers(15,45,size=500));mu=np.exp(offset+x @ np.array([-3.,.2]))
    y=rng.negative_binomial(2,2/(2+mu));weights=rng.integers(1,4,size=500).astype(float)
    beta,status,a=fit_nb2(x,y,offset,weights,p)
    assert status=="fitted"
    def independent(v):
        alpha=np.exp(v[-1]);mean=np.exp(offset+x @ v[:-1]);theta=1/alpha
        return -np.sum(weights*nbinom.logpmf(y,theta,theta/(theta+mean)))
    oracle=minimize(independent,np.r_[beta,np.log(a)],method="BFGS",options={"gtol":1e-5})
    assert abs(independent(np.r_[beta,np.log(a)])-oracle.fun)<1e-5
    np.testing.assert_allclose(np.r_[beta,np.log(a)],oracle.x,atol=1e-4)
    repeated=np.repeat(np.arange(len(y)),weights.astype(int))
    expanded,_,expanded_a=fit_nb2(x[repeated],y[repeated],offset[repeated],np.ones(len(repeated)),p)
    np.testing.assert_allclose(expanded,beta,atol=1e-5)
    assert abs(expanded_a-a)<1e-5
