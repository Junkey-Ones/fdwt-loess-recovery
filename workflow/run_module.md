# 统一运行入口

在项目根目录运行 `.\.venv\Scripts\python.exe -m workflow.run_module`。中文向导使用编号菜单选择运行范围、数据组合和显示方式。选择指定模块后，可以输入一个或多个模块编号。最后核对依赖顺序、运行别名、数据组合、规范和输出路径，再开始预检。重定向时使用逐行提示。

入口读取 params.yaml、specification_matrix.yaml 和 dag.yaml。运行进度和提示经 [终端面板](terminal_panel.md) 写入标准错误，JSON 计划写入标准输出。

当前支持架构预检。科学模块接入、正式运行登记、输入输出哈希核验及续跑写入尚待实现。生产调用返回预检失败。
