# Q2数值求解验收

只读调试脚本，使用2026-11-16_主分析LAI4of5的冻结M5/M6及M2格点—块映射。先核对参数文件与源数据哈希，再重建设计。5/5与4/5的Q2样本、模型和种子相同，因此不重复计算两份相同Q2。

以原种子生成原500次空间块抽样，对RR、ΔSMP分别计算全部抽样并记录最优性证书。读取冻结代码中的旧求解函数，核对主样本及首个旧算法失败的抽样，不更换种子。两线程仅用于调试计算，抽样生成与输出顺序固定。

在项目根目录运行：

```powershell
$env:PYTHONPATH='F:\fdwt-loess-recovery'
.\.venv\Scripts\python.exe notebooks/q2_solver_audit_20261116.py
```

输出metadata/local/q2_solver_validation_20261116.json。该文件不是正式M7模型结果，不含重新发布的联合区间或Holm检验；不可替换旧冻结产物。正式生产仍须经workflow.run_module，在可审计的新代码身份下运行。
