# M3–M10 下游运行

M6根据已冻结的 `variant` 执行5/5主方案或4/5敏感性，暴露簇以 `LAI_window_eligible` 筛选，避免误用仅表示五年完整的 `LAI_full_window`。M7模型清单与恢复风险人候表记录对应暴露版本；风险集本身不因LAI可用年数改变。两方案不自动跨运行别名复用数据。

M3 已接入原生 MODIS 地类和物候前置：无已验收 `grid_support` 登记时，从 MCD12Q1/Q2 自动生成本次运行的格点支撑和审计，随 M3 一起冻结。来源文件逐一计入输入哈希；无需手动执行 `metadata/local/build_grid_support.py`，也不回写共享登记。已有合法标准表仍可复用；无原始文件则保留缺输入退出，部分缺档或来源改变会报错。详见 [M3原生支撑](../src/M3/scr_prepare_native_support.md)。

从仓库根目录通过统一入口运行，例如：

```powershell
.\.venv\Scripts\python.exe -m workflow.run_module route1 --run-alias 2026-11-10_主分析 --dry-run
.\.venv\Scripts\python.exe -m workflow.run_module M3 --run-alias 2026-11-10_主分析
```

正式执行需要同别名的 M0 冻结和通过验收的 M1/M2。模块目录与哈希回执写入 `data/frozen/downstream/{run_alias}/`，状态和日志写入同别名日志目录。任意已冻结的输入内容发生变化时使用新别名。M3 缺少支撑时，下游登记为条件性跳过。

M5 接续候活跃窗修订支持沿用已有别名。统一入口会核对原 M0 快照、M1–M4 回执及产物哈希、来源登记和下游输入引用，并复用通过的上游交接。M5 起的回执引用 `logs/{run_alias}/m5_code_revision.json`，其中保存修订代码、Schema 哈希和上游回执引用。该修订仅在既有上游冻结输入和代码符合兼容范围时启用。

M3 按完整格点时间序列逐批写气候态和候表。M4、M5 投影所需字段，并逐格点处理候序列。M5 汇总区域事件与湿过程后统一生成超级块。M6 逐批汇总日尺度背景气候，M6–M8 只为包含事件的格点加载候序列。M10 按样本保留复算所需的恢复段。

当前附加资料通过 `metadata/local/downstream_inputs.json` 登记。每个键对应一个标准交接数据集，其值包含 `status: accepted`、项目相对 `path`、`sha256` 和非空的 `sources` 列表。每个来源包含原始文件的项目相对路径和 SHA-256。标准表在 `data/interim`，原始文件在 `data/raw`。这份登记依赖资料已经过原生 QA 和覆盖验收。

- `grid_support` 为 JSON 数组，逐格点含 `grid_id`、`vegetation_area_frac`、`native_exclude_frac`、`valid_landcover_years`、`baseline_land_cover` 和 `phenology` 数组。逐年物候项含 `year`、`valid_pixel_area_frac`、`valid_native_pixels`、`segments`。窗段为 ISO 日期起止对。
- `grid_static_covariates` 和 `vegetation_grid_year` 为 Parquet，前者含格点、砂黏比例、高程和坡度，后者沿用 schema 登记。M6 按配置选择掩膜和 QC 版本，再按事件的物候方案连接符合时间及空间覆盖要求的年值。
- `event_master_{product_combo}` 为可选的同支撑替代产品事件表，用于格点匹配。

当前交付覆盖 ERA5-Land 交接、登记标准表和下游计算子集。原生补充产品适配、完整推断模型和规范重跑仍待实现。M10 已接入基于冻结表的[论文图件导出](../src/M10/scr_plot_figures.md)。状态报告区分可运行的描述和待完成项目。

2026-11-17：M7新增Q1删失/年度伴随/联合区间，Q2均值及Q3样本权重、随访、分块尺度、协变量敏感性，均按配置和规范矩阵调度。敏感性输出独立sensitivity_*表，不进入主Holm家族；model_diagnostics报告预设等价界及近似MDE。M7从冻结上下文取得边界并核对100km投影一致性。上游继承支持已继承来源链，只允许明确M7配置投影差异。仍按推进清单报告未验收和条件性未实现项，不自动升级模块总状态。

M7本轮新增PSM配对、平衡与条件差值表，审计进入模块details；RT中位数采用CDF反演并保留开放界。Schema及只读继承白名单同步更新。参见 [代码收尾状态](../docs/M7代码收尾说明_20261117.md)，尚未宣称最终正式验收。
