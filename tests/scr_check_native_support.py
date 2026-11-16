"""M3 原生支撑边界测试；输入合成QA/日期/文件名，输出pytest结果。

作者：Codex；版本：2026-11-15。运行：python -m pytest tests/scr_check_native_support.py。
无生产产物，退出码遵循pytest。
"""
from pathlib import Path
import pytest

from src.M3.scr_prepare_native_support import inventory, overlap, sop_examples


def test_native_support_sop_examples():
    """验证QA解码、跨年双周期、面积中位数和地类并列决策。"""
    sop_examples()


def test_inventory_missing_and_duplicate_tiles():
    """不能将部分年度缺档或重复发布当作完整瓦片输入。"""
    first = Path("MCD12Q1.A2001001.h26v05.061.1.hdf")
    second = Path("MCD12Q1.A2002001.h26v05.061.1.hdf")
    found, tiles = inventory([first, second], "MCD12Q1", [2001, 2002])
    assert len(found) == 2 and tiles == ["h26v05"]
    with pytest.raises(ValueError, match="缺失"):
        inventory([first], "MCD12Q1", [2001, 2002])
    with pytest.raises(ValueError, match="重复"):
        inventory([first, first.with_name("MCD12Q1.A2001001.h26v05.061.2.hdf")], "MCD12Q1", [2001])


def test_nonintersecting_tile_is_empty():
    """不相交瓦片返回空映射，完整覆盖仍由汇总面积闭合检查保证。"""
    result = overlap([{"lat": 36., "lon": 109.}], [102, 34, 115, 41], .1,
                     (-1000000., 1000000., 0., 0., 6371007.181, 2400, 2400))
    assert all(len(column) == 0 for column in result)
