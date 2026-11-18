"""离散中位数不伪造有限上界；区间不受记录顺序影响。"""
import numpy as np
import pytest
from src.M7.scr_discrete_median_interval import discrete_median_interval
from workflow.run_module import DEFAULT_CONFIG,load_config


def test_discrete_interval_open_and_invalid():
    p=load_config(DEFAULT_CONFIG)
    space=np.tile(np.arange(30),20).tolist()
    years=np.repeat(np.arange(20),30).tolist()
    assert discrete_median_interval(np.ones(600)*2,space,years,p)==((1.,None),"upper_unbounded")
    with pytest.raises(ValueError,match="正整数"):
        discrete_median_interval([1.5],[0],[0],p)
    with pytest.raises(ValueError,match="长度"):
        discrete_median_interval([1,2],[0],[0,1],p)
    assert discrete_median_interval([1,2],[0,1],[0,1],p)[1]=="insufficient_years"


def test_discrete_interval_inversion_and_order():
    p=load_config(DEFAULT_CONFIG)
    rng=np.random.default_rng(7)
    space=np.tile(np.arange(40),20)
    years=np.repeat(np.arange(20),40)
    values=rng.choice([1,2,3,4],size=len(space),p=[.1,.6,.2,.1])
    interval,status=discrete_median_interval(values,space.tolist(),years.tolist(),p)
    assert status=="available" and interval[0]<=2<=interval[1]
    order=rng.permutation(len(values))
    assert (interval,status)==discrete_median_interval(values[order],space[order].tolist(),years[order].tolist(),p)
