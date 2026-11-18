# Q1曲线只读验收

读取2026-11-16_主分析LAI4of5的冻结M3/M5及M2空间块，按正式recovery_risk函数分别重建6、12、18候风险集。使用现行配置的89个固定空间块、种子、500次抽样及80%成功门槛，计算曲线与逐候区间；逐项对照旧M7的在险数、恢复数及点估计。输出metadata/local/q1_curve_validation_20261116.json，不发布或覆盖正式结果。

运行：项目根目录设置PYTHONPATH为项目根路径，再执行 `.\.venv\Scripts\python.exe notebooks/q1_curve_audit_20261116.py`。这是调试验收，生产仍经workflow.run_module。
