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
from argparse import Namespace
from io import StringIO

import pytest

from workflow.run_module import DEFAULT_CONFIG, ROOT, build_run_id, load_config, plan_modules, run_module, validate_alias
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
    with pytest.raises(ValueError, match="正式冻结 M0"):
        run_module("route1", run_alias=alias)
    with pytest.raises(ValueError, match="禁止覆盖"):
        run_module("route1", run_alias=alias, overwrite_frozen=True, dry_run=True)


def test_runtime_profiles_are_operational_only(monkeypatch):
    """确认预算随本机内存下调，非法并发在执行前被拦截。"""
    from workflow import runtime

    monkeypatch.setattr(runtime, "memory_gib", lambda: (15.75, 3.5))
    automatic = runtime.resolve_runtime()
    low = runtime.resolve_runtime({"profile": "low"})
    assert automatic["effective"]["memory_gib"] == 2.5
    assert low["effective"]["memory_gib"] == 2.5
    assert low["effective"]["io_workers"] == 1
    assert automatic["reasons"]
    with pytest.raises(ValueError, match="工作进程上限"):
        runtime.resolve_runtime({"profile": "custom", "workers": 1, "memory_gib": 2, "io_workers": 2})
    with pytest.raises(MemoryError, match="内存预算"):
        list(runtime.ordered_tasks(abs, [-1], low, task_gib=3))


def test_progress_estimates_and_terminal_state():
    """以模拟时钟验证滑动速度、停滞、混合估时及结束条件。"""
    from workflow.progress import ProgressEvent, RunProgress, duration, history_medians

    now = [0]
    meter = RunProgress(clock=lambda: now[0])
    meter.configure(["M1", "M2"], {"M1": 50, ("M1", "验收"): 40, "M2": 80})
    meter.event(ProgressEvent("M1", "验收", total=30, unit="文件"))
    meter.observe(meter.snapshot())
    for tick, done in ((5, 4), (10, 7), (15, 14)):
        now[0] = tick
        meter.event(ProgressEvent("M1", "验收", done=done, total=30, unit="文件"))
    snapshot = meter.snapshot()
    assert snapshot["speed"] == 1 and snapshot["eta"] == 16 and snapshot["total_eta"] == 106
    meter.observe(snapshot)
    now[0] = 46
    assert meter.snapshot()["speed"] is None and meter.snapshot()["total_eta"] is None
    meter.event(ProgressEvent("M1", "发布"))
    meter.event(ProgressEvent("M1", "验收结束", state="reused"))
    meter.event(ProgressEvent("M2", "上游未放行", state="conditional_skipped"))
    assert meter.snapshot()["overall"] is None
    meter.finish("passed")
    assert meter.snapshot()["overall"] == 1
    assert meter.forecast_accuracy()["observed_stage"]["estimates"] == 1
    assert meter.forecast_accuracy()["observed_stage"]["median_absolute_error_seconds"] == 15
    assert meter.forecast_accuracy()["historical_total"]["median_absolute_error_seconds"] == 79.5
    assert duration(42) == "42 秒" and duration(492) == "8 分 12 秒" and duration(3960) == "1 小时 06 分"
    records = [dict(signature="同批", timings=[["M1", "", value]]) for value in (12, 16)]
    assert history_medians(records, "同批") == {"M1": 14}
    assert not history_medians(records, "不同批")


def test_progress_interruption_and_failure():
    from workflow.progress import ProgressEvent, RunProgress

    for state in ("interrupted", "failed"):
        meter = RunProgress()
        meter.configure(["M1"], {})
        meter.event(ProgressEvent("M1", "写入", done=10, total=10, unit="文件"))
        assert meter.snapshot()["fraction"] < 1
        meter.finish(state)
        snapshot = meter.snapshot()
        assert snapshot["modules"] == {"M1": state} and snapshot["overall"] is None


def test_wizard_back_help_and_direct_edit(monkeypatch, capsys):
    """返回上一步、查看帮助和在确认页编辑时保留答案。"""
    from workflow.run_module import wizard

    answers = ("1\n帮助\n返回\n\n2026-11-11_向导验收\n\n\n3\n2\n5\n\n1\n1\n")
    monkeypatch.setattr(terminal_panel.sys, "stdin", StringIO(answers))
    with terminal_panel.WizardPanel("测试", "plain") as panel:
        result = wizard(Namespace(config_path=DEFAULT_CONFIG), panel)
    captured = capsys.readouterr()
    assert captured.out == "" and "返回可修改上一组" in captured.err
    assert result.modules == ["route1"] and result.run_alias == "2026-11-11_向导验收"
    assert result.runtime == {"profile": "auto"} and result.progress == "plain" and result.dry_run


@pytest.mark.parametrize("width", [55, 120])
def test_rich_progress_views(width):
    """在两个宽度渲染模块明细、总览和帮助。"""
    from types import SimpleNamespace
    from workflow.progress import ProgressEvent, RunProgress

    output = StringIO()
    console, backend = terminal_panel.rich_console(output)
    console.width = width
    panel = terminal_panel.TerminalPanel(output, interactive=False)
    panel.backend = backend
    panel.live = SimpleNamespace(console=console, update=lambda body, **_: console.print(body))
    meter = RunProgress()
    meter.configure(["M0", "M1"], {})
    meter.event(ProgressEvent("M0", "核对", state="reused"))
    meter.event(ProgressEvent("M1", "验收", done=7, total=20, unit="文件"))
    for view in ("1", "2", "?"):
        panel.draw_run("验收别名", meter.snapshot(), "2 路读取", view)
    rendered = output.getvalue()
    assert "7/20" in rendered and "已复用" in rendered
    assert "估时使用近期速度" in rendered


def test_live_keys_change_only_view():
    from collections import deque
    from types import SimpleNamespace

    keys = deque(["2", "\xe0", "1", "?"])
    live = terminal_panel.LiveStatus("plain", lambda: None)
    live.poll_keys(SimpleNamespace(kbhit=lambda: bool(keys), getwch=keys.popleft))
    assert live.view == "?"
    keys.append("1")
    live.poll_keys(SimpleNamespace(kbhit=lambda: bool(keys), getwch=keys.popleft))
    assert live.view == "1" and not live.stop.is_set()


def test_seed_must_be_registered():
    """种子未登记时禁止生成正式运行身份。"""
    params = load_config(ROOT / "config" / "params.yaml")
    params["random"] = {"seed": None, "seed_id": None}
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
