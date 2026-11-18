"""检验中位数回归的原始—对偶一致性、权重与退化边界。"""
import numpy as np
import pytest
from scipy.optimize import linprog
from src.M7.scr_fit_median import fit_weighted_median


def test_weighted_median_known_solution():
    """有强离群点时仍恢复加权中位数，零权重不参与。"""
    beta, status, audit = fit_weighted_median(np.ones((5, 1)), [0, 2, 3, 100, -999], [1, 5, 1, 1, 0])
    assert status == "fitted" and beta[0] == pytest.approx(2)
    assert audit["relative_gap"] < 1e-7


@pytest.mark.parametrize("seed", [12, 31, 73])
def test_median_dual_matches_independent_primal(seed):
    """与残差正负部的原始LP及另一单纯形算法独立核对最优损失。"""
    rng = np.random.default_rng(seed)
    n = 80
    x = np.column_stack((np.ones(n), rng.normal(size=(n, 3))))
    y = x @ np.array([3., -1., .5, 2.]) + np.round(rng.standard_t(2, n), 1)
    w = rng.integers(0, 4, n).astype(float)
    beta, status, audit = fit_weighted_median(x, y, w)
    assert status == "fitted"
    primal = linprog(np.r_[np.zeros(x.shape[1]), w, w],
                     A_eq=np.column_stack((x, np.eye(n), -np.eye(n))), b_eq=y,
                     bounds=[(None, None)]*x.shape[1]+[(0, None)]*(2*n), method="highs-ds")
    assert primal.success
    assert w @ np.abs(y-x @ beta) == pytest.approx(primal.fun, rel=1e-7, abs=1e-7)
    assert audit["relative_feasibility"] < 1e-7
    repeated = np.repeat(np.arange(n), w.astype(int))
    repeated_beta, status, _ = fit_weighted_median(x[repeated], y[repeated], np.ones(len(repeated)))
    assert status == "fitted"
    assert w @ np.abs(y-x @ repeated_beta) == pytest.approx(primal.fun, rel=1e-7)


def test_median_affine_scale_and_exact_fit():
    """结局平移缩放应按原量纲恢复，零残差目标仍能核验。"""
    x = np.column_stack((np.ones(25), np.arange(25)))
    y = 7-2*x[:, 1]
    for scale in (1e-4, 1, 1e4):
        beta, status, _ = fit_weighted_median(x, 100+scale*y, np.ones(25))
        assert status == "fitted"
        assert beta == pytest.approx([100+7*scale, -2*scale], abs=1e-6)


def test_median_failure_states():
    """无支撑与无效输入不能被标作成功。"""
    x = np.ones((4, 2))
    assert fit_weighted_median(x, np.arange(4), np.ones(4))[1] == "rank_deficient"
    assert fit_weighted_median(x[:, :1], np.ones(4), np.ones(4))[1] == "constant_outcome"
    assert fit_weighted_median(x[:, :1], np.arange(4), np.zeros(4))[1] == "rank_deficient"
    with pytest.raises(ValueError):
        fit_weighted_median(x, np.arange(4), [-1, 1, 1, 1])
