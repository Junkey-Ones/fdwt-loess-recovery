# M3–M10 下游运行

从仓库根目录通过统一入口运行，例如：

```powershell
.\.venv\Scripts\python.exe -m workflow.run_module route1 --run-alias 2026-11-10_主分析 --dry-run
.\.venv\Scripts\python.exe -m workflow.run_module M3 --run-alias 2026-11-10_主分析
```

正式执行需要同别名的 M0 冻结和通过验收的 M1/M2。模块目录与哈希回执写入 `data/frozen/downstream/{run_alias}/`，状态和日志写入同别名日志目录。任意已冻结的输入内容发生变化时使用新别名。M3 缺少支撑时，下游登记为条件性跳过。

M3 按完整格点时间序列逐批写气候态和候表。M4、M5 投影所需字段，并逐格点处理候序列。M5 汇总区域事件与湿过程后统一生成超级块。M6 逐批汇总日尺度背景气候，M6–M8 只为包含事件的格点加载候序列。M10 按样本保留复算所需的恢复段。

当前附加资料通过 `metadata/local/downstream_inputs.json` 登记。每个键对应一个标准交接数据集，其值包含 `status: accepted`、项目相对 `path`、`sha256` 和非空的 `sources` 列表。每个来源包含原始文件的项目相对路径和 SHA-256。标准表在 `data/interim`，原始文件在 `data/raw`。这份登记依赖资料已经过原生 QA 和覆盖验收。

- `grid_support` 为 JSON 数组，逐格点含 `grid_id`、`vegetation_area_frac`、`native_exclude_frac`、`valid_landcover_years`、`baseline_land_cover` 和 `phenology` 数组。逐年物候项含 `year`、`valid_pixel_area_frac`、`valid_native_pixels`、`segments`。窗段为 ISO 日期起止对。
- `grid_static_covariates` 和 `vegetation_grid_year` 为 Parquet，前者含格点、砂黏比例、高程和坡度，后者沿用 schema 登记。植被年值按事件的物候方案连接，同一格点、年份、产品和物候方案只接受一个有效年值。
- `event_master_{product_combo}` 为可选的同支撑替代产品事件表，用于格点匹配。

当前交付覆盖 ERA5-Land 交接、登记标准表和下游计算子集。原生补充产品适配、完整推断模型和规范重跑仍待实现。M10 已接入基于冻结表的[论文图件导出](../src/M10/scr_plot_figures.md)。状态报告区分可运行的描述和待完成项目。
