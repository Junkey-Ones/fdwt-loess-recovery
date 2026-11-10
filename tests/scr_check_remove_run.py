"""脚本名：scr_check_remove_run.py（测试 · MX 清理）
功能简介：验证精确预览、清理、索引保留和并发保护。
作者：Codex
版本：v0.1.0
读取数据：pytest 临时项目。
生成数据：临时项目的回收替身和索引。
其他文件：无。
运行示例：python -m pytest tests/scr_check_remove_run.py
退出码：由 pytest 定义。
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.MX import scr_remove_run as mx
from workflow.freeze_m0 import alias_lock

ALIAS = "2026-11-10_主分析"
OTHER = "2026-11-10_主分析_对照"
COLUMNS = ("run_alias", "run_id", "interim_root", "frozen_root", "outputs_path", "logs_path")


def write_index(root, aliases):
    """建立共享正式编号的运行索引。"""
    index = root / mx.INDEX
    index.parent.mkdir(exist_ok=True)
    rows = [dict(zip(COLUMNS, (alias, "shared", "data/interim", "data/frozen",
                               f"outputs/{alias}", f"logs/{alias}"))) for alias in aliases]
    index.write_bytes(mx.csv_bytes(COLUMNS, rows))


def fixture_paths(root, alias):
    """创建四种标准布局的产物。"""
    paths = [root / base / alias for base in ("outputs", "logs", "data/interim/era5land", "data/frozen/grid")]
    for path in paths:
        path.mkdir(parents=True)
        (path / "artifact").write_text("fixture", encoding="utf-8")
    return set(paths)


def recycler(root):
    """以临时目录移动替代 Windows 系统回收站。"""
    bin_path = root / "test_bin"
    bin_path.mkdir()
    return lambda path: path.rename(bin_path / str(len(list(bin_path.iterdir()))))


def test_exact_alias_and_retry(tmp_path):
    """同编号的其他别名保留，部分失败后可重新确认剩余范围。"""
    write_index(tmp_path, (ALIAS, OTHER))
    own = fixture_paths(tmp_path, ALIAS)
    other = fixture_paths(tmp_path, OTHER)
    plan = mx.preview(tmp_path, ALIAS)
    assert set(plan.paths) == own
    move = recycler(tmp_path)

    def fail_after_first(path):
        if path != plan.paths[0]:
            raise OSError("模拟回收失败")
        move(path)

    with pytest.raises(OSError, match="运行登记保留"):
        mx.cleanup(tmp_path, plan, fail_after_first)
    assert len(mx.read_index(tmp_path)[1]) == 2
    remaining = mx.preview(tmp_path, ALIAS)
    assert len(remaining.paths) == 3
    mx.cleanup(tmp_path, remaining, move)
    assert all(not path.exists() for path in own)
    assert all(path.exists() for path in other)
    assert [row["run_alias"] for row in mx.read_index(tmp_path)[1]] == [OTHER]


def test_unregistered_and_cancel(tmp_path):
    """未登记日志出现在列表中，取消保持目录及索引。"""
    write_index(tmp_path, ())
    path = tmp_path / "logs" / ALIAS
    path.mkdir(parents=True)
    assert mx.list_runs(tmp_path) == [(ALIAS, "")]
    assert mx.recycle_selected(tmp_path, [ALIAS], lambda _: False) is None
    assert path.is_dir()
    assert not (tmp_path / "logs/.run_locks").exists()
    mx.cleanup(tmp_path, mx.preview(tmp_path, ALIAS), recycler(tmp_path))
    assert not path.exists()


def test_confirm_multiple_runs(tmp_path):
    """一次确认可清理正式登记及未登记枝干，列表去重并刷新。"""
    write_index(tmp_path, (ALIAS,))
    owned = fixture_paths(tmp_path, ALIAS) | fixture_paths(tmp_path, OTHER)
    assert dict(mx.list_runs(tmp_path)) == {ALIAS: "shared", OTHER: ""}

    def confirm(plans):
        assert [plan.alias for plan in plans] == [ALIAS, OTHER]
        assert all(path.exists() for path in owned)
        return True

    assert mx.recycle_selected(tmp_path, [ALIAS, OTHER], confirm, recycler(tmp_path)) == [(ALIAS, ""), (OTHER, "")]
    assert not mx.list_runs(tmp_path)


def test_reject_invalid_paths_and_active_run(tmp_path, monkeypatch):
    """非法别名、越界索引、目录联接及运行锁均阻止清理。"""
    write_index(tmp_path, (ALIAS,))
    fixture_paths(tmp_path, ALIAS)
    plan = mx.preview(tmp_path, ALIAS)
    with alias_lock(tmp_path, ALIAS):
        with pytest.raises(ValueError, match="正在运行或清理"):
            mx.cleanup(tmp_path, plan)
    with pytest.raises(ValueError):
        mx.preview(tmp_path, "../" + ALIAS)
    with pytest.raises(ValueError, match="越过"):
        mx.indexed_path(tmp_path, f"outputs/../../{ALIAS}", Path("outputs"), ALIAS)

    link = plan.paths[0] / "linked"
    link.mkdir()
    original = Path.lstat

    def lstat(path):
        info = original(path)
        if path == link:
            return SimpleNamespace(st_mode=info.st_mode,
                                   st_file_attributes=mx.stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(Path, "lstat", lstat)
    with pytest.raises(ValueError, match="目录联接"):
        mx.preview(tmp_path, ALIAS)
