# 验收范围

在项目根目录运行 `python -m pytest` 验证架构契约。各科学模块接入时须落实 SOP §15.1 的 U、E、G、C、L、N、P、T、S、D、R、V 测试，并覆盖事件阈值、缺测、删失和湿窗口的合成序列。生产验收报告写入 outputs/{run_alias}/reports/sop_unit_test_result.csv。架构测试与科学验收分别记录。
