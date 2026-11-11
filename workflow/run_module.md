# 统一运行入口

在项目根目录运行 `.\.venv\Scripts\python.exe -m workflow.run_module`。中文向导使用编号菜单选择运行范围、数据组合和显示方式。选择指定模块后，可以输入一个或多个模块编号。最后核对依赖顺序、运行别名、数据组合、规范和输出路径，再开始预检。重定向时使用逐行提示。

入口读取 params.yaml、specification_matrix.yaml 和 dag.yaml。运行进度和提示经 [终端面板](terminal_panel.md) 写入标准错误，JSON 计划写入标准输出。

单独选择 M0 时，确认页可启动[冻结前审计](../src/M0/scr_audit_protocol.md)或[正式冻结](freeze_m0.md)。审计 JSON 发送到标准输出，阻断摘要及日志路径发送到标准错误。单独选择 M1 或 M2，可用同一个 M0 正式冻结别名执行 [ERA5-Land 主产品链](run_era5land.md)。M3–M10 可执行已接入的[下游计算](run_downstream.md)。

确认前可选择自动、低占用或自定义计算资源。自动档上限为 6 个进程和 2 路读盘，低占用档上限为 2 个进程、4 GiB 和 1 路读盘。自定义档输入进程数、内存 GiB 和读盘并发。生效预算按当前可用内存计算，并为系统预留 1 GiB。预算用于限制任务派发，进程、原生库及写入缓冲的实际内存由操作系统管理。

```powershell
.\.venv\Scripts\python.exe -m workflow.run_module M2 --run-alias 2026-11-11_主分析 --runtime-profile custom --workers 4 --memory-gib 6 --io-workers 2 --dry-run --progress plain
```

Python 入口使用 `runtime={"profile": "custom", "workers": 4, "memory_gib": 6, "io_workers": 2}`。M1 按文件派发，M2 按月派发，均按时间顺序合并。运行配置在 dry-run 的 JSON 和执行日志中显示，与冻结科学参数分开。
