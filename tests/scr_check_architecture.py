"""脚本名：scr_check_architecture.py（测试 · 架构契约）

功能简介：检查依赖、登记结构、别名与预检退出。
作者：Codex
版本：v0.1.0
读取数据：workflow/dag.yaml、config 配置与 metadata 表头。
生成数据：无。
其他文件：pytest 结果输出到终端。
运行示例：python -m pytest tests/scr_check_architecture.py
退出码：由 pytest 定义。
"""
import csv
from io import StringIO

import pytest

from workflow.run_module import ROOT, build_run_id, load_config, plan_modules, run_module, validate_alias
from workflow import terminal_panel


def test_route1_is_independent():
    """确认路线一无需 M8，整体运行将 M8 排在 M9 前。"""
    dag = load_config(ROOT / "workflow" / "dag.yaml")
    route1 = plan_modules(dag, dag["targets"]["route1"])
    full = plan_modules(dag, dag["targets"]["full"])
    assert route1 == [f"M{index}" for index in range(11) if index != 8]
    assert full.index("M8") < full.index("M9")
    assert full.index("M6") < full.index("M8")


@pytest.mark.parametrize("alias", [None, "2026-02-30_测试", "2026-11-10_../a", "2026-11-10_ "])
def test_invalid_alias(alias):
    """拒绝缺失、不合法日期及能改变路径解释的别名。"""
    with pytest.raises(ValueError):
        validate_alias(alias)


def test_preview_and_production_are_distinct():
    """计划可验证，科学模块缺失时生产请求必须失败。"""
    alias = "2026-11-10_架构验收"
    assert run_module("route1", run_alias=alias, dry_run=True)["modules"][-1] == "M10"
    with pytest.raises(ValueError, match="科学模块尚未接入"):
        run_module("route1", run_alias=alias)
    with pytest.raises(ValueError, match="禁止覆盖"):
        run_module("route1", run_alias=alias, overwrite_frozen=True, dry_run=True)


def test_seed_must_be_registered():
    """种子未登记时禁止生成正式运行身份。"""
    params = load_config(ROOT / "config" / "params.yaml")
    with pytest.raises(ValueError, match="随机种子"):
        build_run_id(params, "a" * 64, "b" * 64)
    params["random"] = {"seed": 1, "seed_id": "seed_test"}
    assert build_run_id(params, "a" * 64, "b" * 64) == "v1.3.1__aaaaaaaaaaaa__bbbbbbbbbbbb__seed_test"


def test_metadata_headers_match_registry():
    """核对两个原始数据登记表的空表头。"""
    schemas = load_config(ROOT / "config" / "schema_registry.yaml")["tables"]
    for name in ("source_file_manifest", "source_variable_map"):
        with (ROOT / "metadata" / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
            assert next(csv.reader(handle)) == schemas[name]["columns"]


def test_wizard_plain_retries_without_stdout(monkeypatch, capsys):
    """验证重定向时提示、错误与重试均留在标准错误。"""
    monkeypatch.setattr(terminal_panel.sys, "stdin", StringIO("坏别名\n2026-11-10_验收\n"))
    with terminal_panel.WizardPanel("测试", "plain") as panel:
        assert panel.ask("运行别名", validate_alias) == "2026-11-10_验收"
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("运行别名 [必填]") == 2
    assert "YYYY-MM-DD_短描述" in captured.err


@pytest.mark.parametrize("answer, expected", [("\n", "main"), ("9\n2\n", "check")])
def test_numbered_menu(monkeypatch, capsys, answer, expected):
    """验证编号、默认值和无效编号重试。"""
    monkeypatch.setattr(terminal_panel.sys, "stdin", StringIO(answer))
    with terminal_panel.WizardPanel("测试", "plain") as panel:
        assert panel.menu("数据来源", (
            ("main", "主产品", "主分析"),
            ("check", "替代产品", "稳健性复算"),
        ), "main") == expected
    output = capsys.readouterr().err
    assert "2. 替代产品" in output
    assert ("请输入菜单编号 1–2" in output) == (expected == "check")


def test_wizard_rich_restores_screen_on_interrupt(monkeypatch):
    """用 Rich 实际渲染问题并验证中断时退出备用屏幕和恢复终端模式。"""
    class TerminalStream(StringIO):
        """提供终端标志的内存流，用于捕获控制序列。"""

        def isatty(self):
            return True

    def interrupted_input():
        raise KeyboardInterrupt

    stream = TerminalStream()
    restored = []
    monkeypatch.setattr(terminal_panel.sys, "stdin", TerminalStream())
    monkeypatch.setattr(terminal_panel.sys, "stdout", TerminalStream())
    monkeypatch.setattr(terminal_panel.sys, "stderr", stream)
    monkeypatch.setattr(terminal_panel, "terminal_restore", lambda _: lambda: restored.append(True))
    monkeypatch.setattr("builtins.input", interrupted_input)
    with pytest.raises(KeyboardInterrupt):
        with terminal_panel.WizardPanel("运行向导") as panel:
            panel.ask("运行范围", str, "full")
    output = stream.getvalue()
    assert "运行范围" in output
    assert "\x1b[?1049h" in output and "\x1b[?1049l" in output
    assert restored == [True]
