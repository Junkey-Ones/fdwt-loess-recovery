# 终端面板

组件位于 `workflow.terminal_panel`。从项目根目录运行 `.\.venv\Scripts\python.exe -m workflow.run_module` 进入中文向导。向导分为运行范围、运行版本、数据与规范、显示方式和确认计划五步。彩色面板以紫色标识阶段、青色标识选项编号、绿色标识默认值、黄色标识操作提示、红色标识校验错误。支持中文输入法，退出时恢复终端画面。

## 后续模块如何接入

- 编排入口用 `WizardPanel(title)` 的上下文管理器收集运行控制选项。每道题调用 `panel.ask(prompt, check, default, details=...)`。校验函数返回有效值，输入无效时抛出带中文说明的 `ValueError`。
- 单选题调用 `panel.menu(prompt, options, default, section=...)`。每项提供内部值、中文标签和用途说明，界面自动编号并标记默认项。提交前的确认题汇总模块顺序、数据来源、规范和四类输出路径。
- 运行阶段由编排入口统一管理 `LiveStatus(mode, render)`。先调用 `start()`，在 `finally` 中调用 `close()`。渲染回调通过 `status.panel.draw(title, context, step, detail, statistics, elapsed, fraction)` 显示当前进度，`fraction` 范围为 0–1。回调只读状态快照，科学模块通过运行上下文上报进度。
- `auto` 在支持的终端启用 Rich，重定向时降级为逐行提示。`panel` 要求终端支持光标更新，`plain` 使用逐行输出。面板和提示使用标准错误，结构化结果使用标准输出。

Windows 下建议从 Windows Terminal 启动。向导运行在备用屏幕，答题结束后切换到运行进度显示。
