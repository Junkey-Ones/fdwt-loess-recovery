# M2 ERA5-Land 日与候预处理

读取已通过 M1 的 ERA5-Land 原生文件，生成研究区 0.1° 格点的日和候水量、温度和连续日历。

## 输入与输出

- 输入为同一别名的 M0、M1 哈希回执、ERA5-Land 原生小时场和参数。
- 通量日总量使用次日 00 UTC 的预报累计终值，缺失时段保留为空。逐候通量要求完整日，状态按有效日和连续缺测限制聚合。保留末候 5／6 天实际总量。
- 结果位于 `data/interim/era5land_base/{run_alias}/`，包括 `grid_day_era5land.parquet`、`grid_pentad_base_era5land.parquet`、`grid_manifest.parquet`、`time_pentad_calendar.parquet` 和 `run.json`。
- 地类、物候和静态协变量需要独立来源验收。当前产品表的支撑标识为 `own_full`，适用于原生 ERA5-Land 预处理。

## 执行

月任务读取研究区切片，以单变量约 64 MiB 的解码预算确定每批日数。主进程按月份顺序接收日数组、批量写列式日表，并按连续日历生成候表。任务边界保留次日零点，月末使用下一月首时次，研究期末使用已登记补档。

从项目根目录启动中文向导，选择 M2 并输入正式冻结 M0 的同一别名。批量入口为 `python -m workflow.run_module M2 --run-alias 2026-11-10_主分析`。如果尚无 M1 回执，入口先执行 M1。只有 ERA5-Land 放行后才开始计算。Parquet 表在完整写入、核对原始文件哈希后发布。
