"""脚本名：terminal_panel.py（编排层 · 终端显示）

功能简介：复用工作区指定组件，显示中文帮助与 Rich 运行进度。
作者：参照项目原作者
版本：v0.1.0（移植）
读取数据：入口传入的文本与进度，无数据文件。
生成数据：标准错误中的面板与提示。
其他文件：无。
运行示例：python -m workflow.run_module
退出码：组件无独立退出码。
"""
import argparse
from contextlib import ExitStack
import os
import sys
from threading import Event, Thread
from importlib import import_module
from .progress import LABELS, TERMINAL, duration


class WizardBack(Exception):
    """返回上一组设置。"""


def rich_console(stream):
    """创建复用的 Rich 控制台和组件包名，输出到指定的终端流。"""
    backend = "rich"
    try:
        console_type = import_module("rich.console").Console
    except ModuleNotFoundError as error:
        if error.name != "rich":
            raise
        backend = "pip._vendor.rich"
        console_type = import_module(f"{backend}.console").Console
    environ = dict(os.environ)
    if os.name == "nt" and environ.get("TERM") in ("dumb", "unknown"):
        environ["TERM"] = "xterm"
    console = console_type(file=stream, force_terminal=True, force_interactive=True,
                           color_system="standard", legacy_windows=False, _environ=environ)
    return console, backend


def enable_vt(stream):
    """启用 Windows 虚拟终端序列，返回复原操作。其他终端直接使用 ANSI。"""
    if not stream.isatty():
        return None
    if os.name != "nt":
        return None if os.environ.get("TERM") == "dumb" else lambda: None

    import ctypes
    import msvcrt
    from ctypes import wintypes

    console = ctypes.WinDLL("kernel32", use_last_error=True)
    console.GetConsoleMode.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    console.SetConsoleMode.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    handle = msvcrt.get_osfhandle(stream.fileno())
    previous = wintypes.DWORD()
    if not console.GetConsoleMode(handle, ctypes.byref(previous)):
        return None
    # 开启处理后的输出和虚拟终端控制序列。
    if not console.SetConsoleMode(handle, previous.value | 0x0001 | 0x0004):
        return None
    return lambda: console.SetConsoleMode(handle, previous.value)


class TerminalPanel:
    """用 Rich Live 在当前命令下方维护一块固定的交互区域。"""

    def __init__(self, stream, interactive):
        self.stream = stream
        self.interactive = interactive
        self.restore = self.live = None

    def write(self, text):
        self.stream.write(text)
        self.stream.flush()

    def __enter__(self):
        if self.interactive:
            self.restore = terminal_restore(self.stream)
        if self.restore is None:
            return self
        try:
            console, self.backend = rich_console(self.stream)
            Live = import_module(f"{self.backend}.live").Live
            self.live = Live(console=console, auto_refresh=False, transient=True,
                             redirect_stdout=False, redirect_stderr=False)
            self.live.start()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        try:
            if self.live is not None:
                self.live.stop()
                self.live = None
        finally:
            if self.restore is not None:
                self.restore()
                self.restore = None

    def draw(self, title, context, step, detail, statistics, elapsed, fraction, task=None, *, slots=()):
        """显示当前步骤。进度为零到一的比例，文本输出至标准错误。"""
        if self.live is None:
            lines = (title, context, step, *slots, detail, statistics, elapsed, f"进度 {fraction:.0%}")
            self.write("\n".join(line for line in lines if line) + "\n")
            return

        def component(module, name):
            return getattr(import_module(f"{self.backend}.{module}"), name)

        Group = component("console", "Group")
        Panel = component("panel", "Panel")
        ProgressBar = component("progress_bar", "ProgressBar")
        Text = component("text", "Text")

        body = [Text(context, style="bright_cyan"), Text(step, style="bold bright_white"),
                *(Text(slot, style="bright_blue") for slot in slots), Text(detail),
                ProgressBar(total=1, completed=fraction, width=None,
                            complete_style="bright_green", finished_style="bright_green")]
        if task is not None:
            body.extend((Text("当前任务", style="dim"), ProgressBar(total=1, completed=task, width=None)))
        body.extend((Text(statistics, style="bright_cyan"), Text(elapsed, style="dim")))
        self.live.update(Panel(Group(*body), title=Text(title, style="bold bright_white"),
                               title_align="left", border_style="bright_blue",
                               subtitle=Text("Ctrl+C 安全中断", style="dim")), refresh=True)

    def draw_run(self, alias, snapshot, resources, view):
        """显示同一快照的总览、模块明细或帮助。"""
        event = snapshot["event"]
        modules = snapshot["modules"]
        terminal = snapshot["terminal"]
        stage = " ".join(filter(None, (event.module, event.stage)))
        if event.state in TERMINAL:
            stage += f" · {LABELS[event.state]}"
        elapsed = f"已用 {duration(snapshot['elapsed'])} · 阶段 {duration(snapshot['stage_elapsed'])}"
        finished = sum(state in TERMINAL for state in modules.values())
        overall = snapshot["overall"]
        progress = f"总进度 {min(99, int(overall * 100)) if overall < 1 else 100}%" if overall is not None else ""
        if modules:
            progress = " · ".join(filter(None, (progress, f"已结束 {finished}/{len(modules)} 个模块")))
        eta = f"总剩余时间 {duration(snapshot['total_eta'])}"
        task = ""
        if event.unit:
            scale = 2**20 if event.unit == "字节" else 1
            unit = "MiB" if scale != 1 else event.unit
            completed = f"{event.done / scale:.1f}" if scale != 1 else str(event.done)
            if event.total is not None:
                total = f"{event.total / scale:.1f}" if scale != 1 else str(event.total)
                completed += f"/{total}"
            task = f"阶段 {completed} {unit}"
            if snapshot["speed"] is not None:
                rate_scale = 1 / scale if scale != 1 else 60
                task += f" · {snapshot['speed'] * rate_scale:.1f} {unit}/{'秒' if scale != 1 else '分'}"
            if snapshot["eta"] is not None and event.done < (event.total or 0):
                task += f" · 预计剩余 {duration(snapshot['eta'])}"
        if snapshot["stale"] >= 30 and not terminal and event.state == "running":
            task = " · ".join(filter(None, (task, f"{duration(snapshot['stale'])} 未收到进度更新")))
        final = LABELS.get(terminal, "")
        lines = (final, stage, event.detail, progress, task, elapsed, eta)
        if self.live is None:
            self.write(" · ".join(filter(None, lines)) + "\n")
            return

        def component(module, name):
            return getattr(import_module(f"{self.backend}.{module}"), name)

        Text = component("text", "Text")
        Group = component("console", "Group")
        Panel = component("panel", "Panel")
        Bar = component("progress_bar", "ProgressBar")
        Columns = component("columns", "Columns")
        Table = component("table", "Table")

        def progress_bar(fraction):
            grid = Table.grid(expand=True)
            grid.add_row(Bar(total=1, completed=fraction))
            return grid

        rows = [Text(alias, style="bright_cyan"), Text(stage, style="bold bright_white")]
        for line in (final, event.detail, progress, task, elapsed, eta, resources):
            if line:
                rows.append(Text(line))
            if line and line == progress and overall is not None:
                rows.append(progress_bar(overall))
            if line and line == task and snapshot["fraction"] is not None:
                rows.append(progress_bar(snapshot["fraction"]))
        colors = {"passed": "green", "reused": "cyan", "failed": "red", "interrupted": "red", "running": "yellow"}
        states = Group(Text("模块状态", style="bold"), *(
            Text(f"{module}  {LABELS.get(state, state)}", style=colors.get(state, "dim"))
            for module, state in modules.items()))
        overview = Group(*rows)
        width = self.live.console.width
        if view == "?":
            body = Group(Text("1 总览    2 模块明细    ? 帮助"),
                         Text("Ctrl+C 安全中断"), Text("估时使用近期速度和匹配的本机运行记录。"))
        elif view == "2":
            body = Columns([states, overview], equal=True, expand=True) if width >= 100 else Group(states, overview)
        else:
            body = Columns([overview, states], equal=True, expand=True) if width >= 100 and modules else overview
        self.live.update(Panel(body, title="黄土高原 FD-WT", title_align="left", border_style="bright_blue",
                               subtitle="1 总览 · 2 模块 · ? 帮助 · Ctrl+C 中断"), refresh=True)


def terminal_restore(stream):
    """探测显示流是否支持光标更新，返回原终端模式的恢复操作。"""
    try:
        return enable_vt(stream)
    except (OSError, ValueError):
        return None


class WizardPanel:
    """在同一终端画面逐题显示选项，保留终端原生输入和中文输入法。"""

    def __init__(self, title, mode="auto"):
        self.title = title
        self.mode = mode
        self.stack = ExitStack()
        self.console = None
        self.navigation = False
        self.answers = {}

    def __enter__(self):
        if self.mode == "plain" or not (sys.stdin.isatty() and sys.stdout.isatty()):
            return self
        restore = terminal_restore(sys.stderr)
        if restore is None:
            return self
        with ExitStack() as setup:
            setup.callback(restore)
            console, backend = rich_console(sys.stderr)
            screen = setup.enter_context(console.screen(hide_cursor=False))
            self.console = screen.console
            self.panel_type = import_module(f"{backend}.panel").Panel
            self.text_type = import_module(f"{backend}.text").Text
            self.group_type = import_module(f"{backend}.console").Group
            self.stack = setup.pop_all()
        return self

    def __exit__(self, *exc):
        return self.stack.__exit__(*exc)

    def menu(self, prompt, options, default=None, *, section="运行设置", check=None, details=()):
        """显示编号菜单。每项包含内部值、中文标签和用途说明。"""
        keys = {str(index): key for index, (key, _, _) in enumerate(options, 1)}
        labels = {key: label for key, label, _ in options}
        saved = self.answers.get(prompt) if self.navigation else None
        default = keys.get(saved, saved) if saved and keys.get(saved, saved) in labels else default
        rows = tuple((number, label, description, key == default)
                     for number, (key, label, description) in zip(keys, options))
        default_number = next((number for number, key in keys.items() if key == default), None)

        def select(value):
            key = keys.get(value, value)
            if key not in labels:
                raise ValueError(f"请输入菜单编号 1–{len(options)}。")
            return check(key) if check else key

        return self.ask(prompt, select, default_number, section=section, details=details,
                        hint="输入编号后回车", rows=rows)

    def ask(self, prompt, check, default=None, *, details=(), section="运行设置", hint="", rows=()):
        """显示当前题与详情，返回校验后的输入。校验失败时在同一题显示原因。"""
        remember = self.navigation and not section.startswith("05")
        if remember:
            default = self.answers.get(prompt, default) if not rows else default
        suffix = f" [默认：{default}]" if default is not None else " [必填]"
        instruction = hint or "输入内容后回车"
        if default is not None:
            instruction += " · 直接回车使用默认值"
        if self.navigation:
            instruction += " · 返回 / 帮助 / 退出"
        error = ""
        while True:
            if self.console is not None:
                text = self.text_type
                body = [text(section, style="bold bright_magenta"), text(),
                        text(prompt, style="bold bright_white")]
                body.extend(text(line, style="bright_cyan") for line in details)
                for number, label, description, is_default in rows:
                    row = text(f"  {number}  ", style="bold bright_cyan")
                    row.append(label, style="bold bright_white")
                    if is_default:
                        row.append("  默认", style="bold bright_green")
                    if description:
                        row.append(f"  ·  {description}", style="white")
                    body.append(row)
                body.extend((text(), text(instruction, style="bright_yellow")))
                if error:
                    body.append(text(f"请修正  {error}", style="bold bright_red"))
                self.console.clear()
                self.console.print(self.panel_type(self.group_type(*body),
                                                   title=text(self.title, style="bold bright_white"),
                                                   border_style="bright_blue", title_align="left",
                                                   subtitle=text("Ctrl+C 退出", style="dim")))
                self.console.print(text("选择 > " if rows else "输入 > ", style="bold bright_cyan"), end="")
            else:
                options = tuple(f"  {number}. {label} · {description}" for number, label, description, _ in rows)
                lines = (section, f"{prompt}{suffix}", *details, *options, instruction, error)
                message = "\n".join(line for line in lines if line)
                end = "" if sys.stdin.isatty() else "\n"
                sys.stderr.write(f"{message}\n请输入：{end}")
                sys.stderr.flush()
            if sys.stdin.isatty():
                value = input()
            else:
                value = sys.stdin.readline()
                if not value:
                    raise EOFError
            try:
                value = value.strip() or default
                if self.navigation:
                    if value == "返回":
                        raise WizardBack
                    if value == "退出":
                        raise KeyboardInterrupt
                    if value == "帮助":
                        error = "输入编号或题目要求的内容。返回可修改上一组，退出结束向导。"
                        continue
                result = check(value)
                if remember:
                    self.answers[prompt] = value
                return result
            except ValueError as failure:
                error = str(failure)


def check_progress(mode):
    """校验显式面板模式的终端能力，返回可用的显示模式。"""
    if mode == "panel":
        restore = terminal_restore(sys.stderr)
        if restore is None:
            raise ValueError("当前终端不支持光标更新。请选择 auto 或 plain，或在 Windows Terminal 中运行。")
        restore()
    return mode


def validate_progress(parser, args):
    """将显示模式校验失败报告为中文命令行错误。"""
    if not args.dry_run:
        try:
            check_progress(args.progress)
        except ValueError as error:
            parser.error(str(error))


class LiveStatus:
    """为阻塞式读取定时刷新，由入口更新状态并处理退出。"""

    def __init__(self, mode, render):
        self.mode = mode
        interactive = (mode != "plain" and sys.stderr.isatty()
                       and (mode == "panel" or (sys.stdin.isatty() and sys.stdout.isatty())))
        self.panel = TerminalPanel(sys.stderr, interactive)
        self.render = render
        self.view = "1"
        self.keyboard = os.name == "nt" and sys.stdin.isatty() and sys.stderr.isatty()
        self.stop = Event()
        self.thread = Thread(target=self.refresh, daemon=True)

    def start(self):
        self.panel.__enter__()
        try:
            self.render()
            self.thread.start()
        except BaseException:
            self.close()
            raise

    def refresh(self):
        interval = 0.25  # technical constant
        while not self.stop.wait(interval):
            if self.keyboard and self.panel.live is not None:
                import msvcrt

                self.poll_keys(msvcrt)
            self.render()

    def poll_keys(self, keyboard):
        """在 Windows 控制台消费视图快捷键和扩展键序列。"""
        while keyboard.kbhit():
            key = keyboard.getwch()
            if key in ("\x00", "\xe0"):
                keyboard.getwch()
            elif key in ("1", "2", "?"):
                self.view = key

    def close(self):
        self.stop.set()
        try:
            if self.thread.ident is not None:
                self.thread.join()
        finally:
            self.panel.__exit__(None, None, None)


class ChineseHelp(argparse.RawDescriptionHelpFormatter):
    """以中文标注命令用法。"""

    def add_usage(self, usage, actions, groups, prefix=None):
        super().add_usage(usage, actions, groups, "用法：" if prefix is None else prefix)


class ChineseParser(argparse.ArgumentParser):
    """将常见命令行输入错误转换成可操作的中文提示。"""

    def error(self, message):
        for source, target in (("the following arguments are required:", "缺少必填参数："),
                               ("unrecognized arguments:", "无法识别的参数："),
                               ("invalid choice:", "无效取值："), ("(choose from ", "(允许取值："),
                               ("invalid int value:", "请输入整数，收到："),
                               ("not allowed with argument", "不能同时使用"),
                               ("expected one argument", "后面需要填写一个值"), ("argument ", "参数 ")):
            message = message.replace(source, target)
        self.print_usage(sys.stderr)
        self.exit(2, f"参数错误：{message}\n运行 {self.prog} --help 查看示例。\n")


