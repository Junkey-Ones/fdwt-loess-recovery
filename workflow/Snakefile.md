# Snakemake 编排

从项目根目录读取 dag.yaml、params.yaml 和 Snakemake 的运行控制参数。预期产物是 logs/{run_alias}/module_io_{module}.json，由正式模块入口写入。高级入口可用 Snakemake 的 dry-run 检查依赖。架构阶段的 Python 入口支持计划预检，正式 Snakemake 作业须等待科学模块及运行登记接入。
