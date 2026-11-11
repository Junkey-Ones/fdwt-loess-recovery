# Snakemake 编排

从项目根目录执行。选择 M0 时创建正式冻结，下游目标使用同一别名和 M0 回执。每个目标由一个 Snakemake 作业调用统一入口，入口按 dag.yaml 决定模块顺序并核验回执。Snakemake 追踪目标完成记录，正式回执由模块自行发布。需要重新核验已有目标时使用 `--forcerun selected_workflow`。

```powershell
.\.venv\Scripts\python.exe -m snakemake --snakefile workflow/Snakefile --dry-run --cores 1 --config target=M0 run_alias=2026-11-11_主分析
```

可以通过 Snakemake 的 `--configfile` 提供 `runtime` 映射，字段与统一 Python 入口相同。
