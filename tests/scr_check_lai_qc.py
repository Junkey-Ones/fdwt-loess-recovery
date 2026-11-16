"""M6 气溶胶修订验证。

作者：Codex。版本：2026-11-15。
输入：全部质量字节组合及合成LAI值；输出：pytest结果，无生产输出。
运行：python -m pytest tests/scr_check_lai_qc.py；退出码遵循pytest。
"""
import numpy as np
import pytest

from src.M6.scr_prepare_vegetation import lai_qc


@pytest.mark.parametrize("strict", [False, True])
def test_aerosol_only_difference(strict):
    """穷举两层QA的65536组合，确保只释放气溶胶单项且与审计算法等价。"""
    qc = np.repeat(np.arange(256, dtype=np.uint8), 256)
    extra = np.tile(np.arange(256, dtype=np.uint8), 256)
    raw = np.full(qc.shape, 30, dtype=np.uint8)
    old = lai_qc(raw, qc, extra, strict=strict)
    new = lai_qc(raw, qc, extra, strict=strict, allow_aerosol=True)
    audited = lai_qc(raw, qc, extra & np.uint8(247), strict=strict) & (extra != 255)
    assert np.array_equal(new, audited)
    assert np.all(~old | new)
    assert np.all(((extra[new & ~old] >> 3) & 1) == 1)
    assert np.any(new & ~old)
    # 单独解码各位，验证云、雪、阴影、地类和反演算法限制仍成立。
    expected = ((qc & 1) == 0) & (((qc >> 2) & 1) == 0) & (((qc >> 3) & 3) == 0)
    expected &= (qc >> 5) <= (0 if strict else 1)
    expected &= (extra & 3) <= 1
    for bit in (2, 4, 5, 6):
        expected &= ((extra >> bit) & 1) == 0
    expected &= (qc != 255) & (extra != 255)
    assert np.array_equal(new, expected)


def test_fill_and_valid_lai_range():
    """释放气溶胶不能复活LAI填充值或原始QA填充值。"""
    raw = np.array([0, 100, 101, 255, 30, 30], dtype=np.uint8)
    qc = np.array([0, 32, 0, 0, 255, 0], dtype=np.uint8)
    extra = np.array([8, 8, 8, 8, 8, 255], dtype=np.uint8)
    assert lai_qc(raw, qc, extra, allow_aerosol=True).tolist() == [True, True, False, False, False, False]
