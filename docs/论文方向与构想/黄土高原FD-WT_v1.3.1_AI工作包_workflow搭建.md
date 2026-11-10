# 黄土高原 FD-WT v1.3.1——AI 工程规格工作包与 Workflow 搭建规范

> **用途**：供 AI 或开发人员搭建完整、可复现、可断点续跑的 FD-WT workflow，并实现 M0—M10 可复用程序模块。
>
> **规格来源**：仅抽取并工程化 v1.3.1 五份文档中已经冻结或明确暂时锁定的内容；本文件不改变研究问题、估计对象、结局排序、样本时期、主暴露、模型或阈值。
>
> **权威顺序**：估计对象、结局排序、多重检验和偏离纪律以《预注册文档》为准；原生数据、QC、公式和字段语义以《详细技术手册》为准；模块依赖与责任边界以《模块化思路理解》为准。
>
> **冻结边界**：本规格保留“事件前五个完整年 LAI”主设计，不把讨论中的“三年背景＋前四候临近状态”等其他方案写入主链。研究区矢量、站点清单及使用权、可选环流具体下载字段仍属暂时锁定项。
>
> **文档版本**：v1.3.1-engineering-full；对应科学协议冻结日期 2026-11-02。

## 0. 给 AI 的最高优先级工程指令

### 0.1 必须交付的系统

1. 一个以 DAG 编排的 M0—M10 工作流，可整体运行、单模块运行、按依赖重跑和断点续跑。
2. 每个模块一个独立程序入口；科学逻辑、参数和文件路径解耦。
3. 所有阈值、窗口、样本门槛、敏感性开关和随机种子统一从 `params.yaml` 读取，代码中不得出现科学参数的魔法数字。
4. 每个模块必须执行：读取参数 → 校验上游冻结文件 → 计算 → schema 校验 → 写出新文件 → 原子冻结 → 写运行日志。
5. 四套产品组合和各项敏感性必须由配置驱动，不得复制一套代码后手工改数字。

### 0.2 不可违反的工程铁律

- **参数单一来源**：同一参数只能在 `params.yaml` 定义一次；模块只按键读取。
- **上游只读**：任何下游模块不得回写、覆盖或修补上游冻结表。
- **幂等**：相同参数、输入、代码版本和随机种子必须产生内容一致的输出；时间戳不参与科学结果哈希。
- **原子写出**：先写临时文件，校验通过后再重命名为冻结文件；失败时不得留下貌似完整的下游表。
- **失败显式化**：缺文件、QC 失败、字段冲突、主键重复和单元测试失败均须停止相应主链或按预设规则记缺失，禁止静默跳过。
- **样本流完整**：每次过滤均记录过滤前后数量、排除原因和对应模块；不得只保留最终样本数。
- **未知不等于阴性**：窗口不完整的 P-term、F_R、F_Z 和路线二急转类型必须记未知，不得填 0。
- **缺失不等于零**：任何缺测均用空值加原因字段表示，禁止以 0 填充土壤水、LAI、NDVI、降水或结局。
- **不按结果改设计**：不得根据 p 值、效应方向、区间宽窄或故事吸引力改变事件定义、暴露窗口、协变量、样本或模型。
- **科学表与展示表分离**：论文表格和图只能由冻结结果表生成，禁止手工修改数值。

### 0.3 冻结科学措辞的程序断言

输出文本和自动摘要不得出现以下错误：

- 把 F_R 与 P-term 的构造嵌套称为独立发现或独立验证；
- 把 F_R／F_Z 双算法称为双数据源独立验证；
- 把 `W=0.5` 称为“95% 极端”，或把 `α=3.2` 称为黄土高原物理常数；
- 把已恢复事件的 RT 条件分布推广到全部骤旱；
- 把 E1b 称为全部骤旱总体风险；
- 把路线二 C 称为已经转变的常规干旱，或把删失称为第四出口；
- 把 LAI 写成光合生理功能、生态恢复结局或退耕还林的独立因果效应；
- 把 PSM、GAM、随机森林、SHAP 或暴露时间在前写成充分因果识别；
- 使用“首次”“国际空白”“顶刊级”“必然发表”等预设承诺。

## 1. 研究骨架、模块边界与执行状态

### 1.1 不可变科学骨架

- **路线一，必须独立完成**：骤旱识别 → 恢复动力学 → 极端降水接续与时间差 → 事件前 LAI／深层水关联和效应修饰 → 跨产品稳健性。
- **路线二，可拆卸探索扩展**：全部合格骤旱在固定 H=12 候内进入 A／B／C 三出口；其失败、降级或退出不影响路线一。
- **结局层级**：
  1. RT、恢复风险、ΔSMP、RR；
  2. F_R、Lag_P、Lag_FR、Offset_FR；
  3. 事件前 LAI／深层水主效应与交互；
  4. F_Z、DFAI、E1a、P／F 集合质控、影响面积和可选环流合理性。

### 1.2 四层研究时期

| 数据层 | 冻结时期 | 工程实现要求 |
|---|---|---|
| 总体事件、恢复与急转库 | 2000—2023 | 不因 LAI 缺失删除 2000—2007 事件 |
| LAI 完整年序列 | 2003—2023 | 2002 年仅可作部分年诊断，不进入完整年暴露 |
| 五年 LAI 事件前暴露模型 | 2008—2023 | 2008 年事件使用 2003—2007 年 |
| LAI／NDVI 直接共同样本 | 2008—2023 | 同事件、同五年窗、同掩膜、同模型比较 |

NDVI 五年暴露从 2005 年事件起可完整；所有产品均止于 2023 年，不得混用未审计实时产品延长主序列。

### 1.3 模块运行状态枚举

每个模块和条件性分析必须写入以下状态之一：

| 状态 | 含义 |
|---|---|
| `not_run` | 尚未运行 |
| `running` | 正在运行，不是冻结结果 |
| `passed` | 运行、校验和验收全部通过 |
| `descriptive_only` | 样本或数据不足，只生成描述性结果 |
| `conditional_skipped` | 预设条件不满足，未生成模型结果 |
| `exited` | 按冻结退出规则退出，已生成审计与退出理由 |
| `failed` | 技术失败或校验失败，下游不得运行 |

空结果表也必须保留 schema、主键和状态说明；不得用伪造数值填满模板。

## 2. DAG、运行批次与依赖契约

### 2.1 主 DAG

```text
M0 协议、schema、版本与空偏离日志冻结
  ↓
M1 原始数据、官方元数据与变量映射审计
  ↓
M2 原生 QC、单位／符号、日／候、土层与空间预处理
  ↓
M3 静态掩膜、共同支撑、动态物候与各产品独立气候态
  ↓
M4 全部合格骤旱事件库、右删失与区域 cluster
  ↓
M5 恢复、P-term、F_R／F_Z、Lag、分支强度与湿过程
  ├──→ M6 LAI／NDVI／深层水暴露与暴露簇审计
  │       ↓
  │      M7 路线一 Q1／Q2／Q3、恢复风险、趋势与主结果
  │
  └──→ M8a 路线二事件—候随访构造
          ↓（可选连接 M6 暴露）
         M8b 三出口门槛判定、原因别风险模型或退出

对四套产品组合及 GLDAS 原生 0.25° 分别重复 M2—M8 的适用部分
  ↓
M9 跨产品匹配、站点分轨验证、规范曲线与一致性汇总
  ↓
M10 独立复核、样本流、偏离审计、最终图表与措辞检查
```

### 2.2 编排器必须识别的依赖

- M7 不得读取 M8 的任何输出；路线一不依赖路线二。
- M8a 只读 M4／M5 冻结表；M8b 可选读取 M6，但不得反向修改暴露。
- M9 只汇总已经完成独立气候态和独立事件识别的产品运行，不得在匹配阶段共享 P95 或 SMP 阈值。
- M10 只能读取冻结产物；发现不一致时退回责任模块并触发新 `run_id`，禁止直接改表。
- 一个模块输入文件的哈希变化时，其全部下游依赖自动失效并重跑。

### 2.3 四种运行批次

| 批次 | 标识示例 | 用途 |
|---|---|---|
| 主产品运行 | `era5land__era5land` | 路线一主分析 |
| 陆面复算 | `gldas21__gldas21` | 替代土壤水与降水链 |
| 降水替换 | `era5land__chirps20` | 替换降水源 |
| 双替换 | `gldas21__chirps20` | 同时替换土壤水和降水源 |

GLDAS 另以 `grid_version=gldas_native_025` 完整复算。0.25° 重网格到 0.1° 只称面积保守重网格，不增加独立信息。

## 3. 全局命名、时间、主键和文件规范

### 3.1 名称规范

- 新增工程字段、文件名和目录名一律使用小写 `snake_case`。
- 以下已冻结科学字段保留原拼写，不得擅自改名：`RT`、`delta_SMP`、`RR`、`P_term`、`F_R`、`F_R_subtype`、`F_Z`、`Lag_P`、`Lag_FR`、`Offset_FR`、`DFAI`、`DFAI_alpha`、`LAI_base`、`LAI_trend`、`NDVI_base`、`NDVI_trend`。
- 单位尽量写入字段名或单位注册表，例如 `p_mm`、`lai_mean`、`slope_deg`；SMP 为百分位，RR 为百分位／候。
- 同一语义不得出现多个别名；展示层中文名称通过数据字典映射，不回写科学表。
- 原始文件只读保存，原始字段名与项目规范字段名通过 `source_variable_map` 连接。

### 3.2 产品、版本和方案标识

| 标识                        | 冻结值或规则                                                                 |
| ------------------------- | ---------------------------------------------------------------------- |
| `protocol_version`        | `v1.3.1`                                                               |
| `soil_product`            | `era5land`、`gldas21`                                                   |
| `precip_product`          | `era5land`、`gldas21`、`chirps20`                                        |
| `product`／`product_combo` | `{soil_product}__{precip_product}`                                     |
| `grid_version`            | 主网格 `era5land_010`；原生复算 `gldas_native_025`                             |
| `support_id`              | `own_full` 或 `common_support`，并附具体成员哈希                                 |
| `phenology_mode`          | `dynamic`、`fixed_apr_sep`、`climatology`、`complete_case`、`single_cycle` |
| `termination_rule`        | `smp_gt20`、`smp_gt40`                                                  |
| `duration_definition`     | `total_duration`、`development_duration`                                |
| `exposure_version`        | 至少能唯一表示指标、窗长、完整年规则、物候和掩膜版本，如 `lai5_full5_dynamic`                      |
| `run_id`                  | `v1.3.1__{params_hash12}__{code_hash12}__{seed_id}`                    |

`seed_id` 对应的实际随机种子须在 M0 看结局前固定并记录；v1.3.1 未指定某个数值，本规格不代为补造。

### 3.3 连续时间索引

所有跨年和窗口运算必须使用连续候索引，不得仅用 `year+pentad` 做字符串拼接：

```text
t_abs = (year - 2000) * 73 + pentad
pentad ∈ [1, 73]
```

- `t_s`、`t_min`、`t_e`、`t_P95`、`t_w` 在科学计算中均保存为整数 `t_abs`。
- 同时保留对应 `year`、`pentad`、`start_date`、`end_date`，便于审计。
- `t_e+1`、`t_e+2`、候 ±1 和前 4 候均基于 `t_abs` 运算，允许跨年。
- 第 73 候保留实际 `n_days=5/6`，闰年不得丢弃第 366 天。
- ERA5-Land 使用 UTC；其他产品及时制由官方元数据核验后登记，站点另存原时制与映射规则。

### 3.4 稳定 ID 规则

| ID | 生成规则 | 稳定性要求 |
|---|---|---|
| `grid_id` | 在冻结 `grid_manifest` 中按纬度降序、经度升序排序后生成 `g000001` 等 | 网格版本不变时不得重排 |
| `episode_id` | `{product_combo}__{duration_definition}__{termination_rule}__{grid_id}__{t_s}` | 同一事件跨模块不变 |
| `cluster_id` | 区域连通结果按最早 `t_abs`、最小 `grid_id` 确定性排序编号 | 重跑不得随机变化 |
| `wet_process_id` | 按产品、格点及连续合格湿候确定性生成；区域合并另存连接表 | 不得按结果显著性合并 |
| `LAI_exposure_cluster` | `lai__{grid_id}__{year}` | 同一 `grid_id×year` 共享 |
| `block_id` | 由冻结 100 km 空间块算法生成 | 保存几何与参数哈希 |
| `superblock_id` | 将跨块 `cluster_id`／`wet_process_id` 连接的块做连通合并 | 保存成员块列表 |

### 3.5 空值、布尔值和状态字段

- 数值缺失使用空值，不使用 `-9999`、0 或无穷大替代。
- 布尔字段使用可空 `0/1`；未知时为空，并配 `*_status` 或 `*_reason`。
- 建议统一状态：`complete`、`incomplete`、`unknown`、`not_applicable`、`missing_qc`、`missing_source`、`outside_support`。
- 每个关键结局至少配套一个状态字段，例如 `F_R` 对应 `F_R_status`，`P_term` 对应 `P_term_status`。
- 分类字段使用受控词表；新增词值须升级 schema 版本，不得在不同模块中临时创造同义字符串。

### 3.6 文件格式、分区与冻结

| 数据类型 | 格式 | 规则 |
|---|---|---|
| 大型格点—日／候、事件—候表 | Parquet | 按产品、年份等分区；字段类型固定 |
| 小型配置、字典和清单 | YAML／JSON／CSV | UTF-8；CSV 仅用于小规模审计和交换 |
| 栅格／空间场 | NetCDF／GeoTIFF | 保存 CRS、网格、单位、时间和缺失值元数据 |
| 矢量与 footprint | GeoPackage／GeoJSON | 保存面积计算所需 CRS 与版本 |
| 模型对象 | 可序列化模型文件＋JSON 摘要 | 模型对象不能替代效应结果表 |
| 日志 | JSONL／CSV | 每次运行追加；冻结后只读 |

推荐目录：

```text
fdwt_v1.3.1/
├── config/
│   ├── params.yaml
│   ├── schema_registry.yaml
│   └── specification_matrix.yaml
├── metadata/
│   ├── source_file_manifest.csv
│   ├── source_variable_map.csv
│   ├── protocol_freeze.json
│   └── run_manifest.json
├── data/
│   ├── raw/                 # 只读，不进入公开结果包时可仅保存清单与哈希
│   ├── interim/{run_id}/    # 可重建，不作为下游最终依据
│   └── frozen/{run_id}/     # 通过校验后的模块交接表
├── outputs/{run_id}/
│   ├── tables/
│   ├── figures/
│   ├── models/
│   └── reports/
└── logs/{run_id}/
```

## 4. 数据源、原生变量与项目规范字段

### 4.1 数据注册总表

| 产品代码 | 产品与版本 | 原生尺度 | 本项目角色 | 状态 | DOI |
|---|---|---|---|---|---|
| `era5land` | ERA5-Land | 0.1°、小时 | 主 SMP、P、ET、R、W、深层水和温度 | 冻结 | https://doi.org/10.5194/essd-13-4349-2021；https://doi.org/10.24381/cds.e2161bac |
| `gldas21` | GLDAS-2.1 Noah 主生产流 | 0.25°、3 小时 | 跨陆面产品复算与深层水 | 冻结；不与 Early Product 混用 | https://doi.org/10.5067/E7TYRXPJKWOQ；https://doi.org/10.1175/BAMS-85-3-381 |
| `chirps20` | CHIRPS v2.0 | 0.05°、日 | 独立降水源敏感性 | 冻结 | https://doi.org/10.1038/sdata.2015.66 |
| `mcd15a3h061` | MCD15A3H.061 | 500 m、4 天；2002-07-04 起 | 主 LAI 暴露 | 冻结 | https://doi.org/10.5067/MODIS/MCD15A3H.061 |
| `mod13q1061` | MOD13Q1.061 | 250 m、16 天；2000-02-18 起 | NDVI 稳健性 | 冻结 | https://doi.org/10.5067/MODIS/MOD13Q1.061 |
| `mcd12q2061` | MCD12Q2.061 | 500 m、年 | 动态物候活跃窗 | 冻结 | https://doi.org/10.5067/MODIS/MCD12Q2.061；https://doi.org/10.1016/j.rse.2019.111356 |
| `mcd12q1061` | MCD12Q1.061 | 500 m、年 | 土地掩膜与地类协变量 | 冻结 | https://doi.org/10.5067/MODIS/MCD12Q1.061 |
| `soilgrids250m` | SoilGrids250m | 250 m、静态 | 0—30 cm 砂粒／黏粒协变量 | 下载版本与校验值在 M1 冻结 | https://doi.org/10.1371/journal.pone.0169748 |
| `nasadem001` | NASADEM_HGT.001 | 约 30 m、静态 | 高程与派生坡度 | 冻结 | https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001 |
| `era5_circulation` | ERA5 单层／压力层 | 下载后登记 | 可选环流合理性 | 变量族冻结，具体字段暂时锁定 | https://doi.org/10.1002/qj.3803 |
| `station_sm` | 土壤水站点 | 原生层深与时制 | 旱相分轨验证 | 清单和使用权暂时锁定 | 无统一 DOI；逐站点来源登记 |
| `station_p` | 降水站点 | 原生时制与单位 | 湿相分轨验证 | 清单和使用权暂时锁定 | 无统一 DOI；逐站点来源登记 |

GLEAM、MOD16、CMFD、Noah-MP 离线实验和 CMIP6 因子试验不属于 v1.3.1 必需数据链，主程序不得自动下载或接入。

### 4.2 ERA5-Land 字段映射

| 原生变量名 | 项目规范字段 | 单位／转换 | 用途 |
|---|---|---|---|
| `volumetric_soil_water_layer_1` | `sm_l1_m3m3` | m³/m³ | 0—7 cm 土层计算 |
| `volumetric_soil_water_layer_2` | `sm_l2_m3m3` | m³/m³ | 7—28 cm 土层计算 |
| `volumetric_soil_water_layer_3` | `sm_l3_m3m3` | m³/m³ | 28—100 cm 土层计算 |
| `volumetric_soil_water_layer_4` | `sm_l4_m3m3` | m³/m³ | 100—289 cm 深层状态 |
| `total_precipitation` | `p_raw_m` → `p_mm` | 按累计类型审计；m×1000 | 候总降水、P95、P-term、F_R |
| `total_evaporation` | `et_raw_m` → `et_loss_mm` | 按元数据判断符号；不得重复取负 | 水量平衡 B |
| `potential_evaporation` | `pet_raw_m` → `pet_loss_mm` | 同上 | SESI／SESR 敏感性，非主链必需 |
| `surface_runoff` | `runoff_surface_raw_m` → `runoff_surface_mm` | m×1000 | R 的地表部分 |
| `subsurface_runoff` | `runoff_subsurface_raw_m` → `runoff_subsurface_mm` | m×1000 | R 的地下部分 |
| `2m_temperature` | `t2m_k` → `t2m_c` | K−273.15 | 4—9 月均温协变量 |

派生字段：

```text
sm_0_100_mm = 1000 × (0.07×sm_l1_m3m3 + 0.21×sm_l2_m3m3 + 0.72×sm_l3_m3m3)
sm_deep_mm = ERA5-Land 第4层对应深层储量表达；层深固定100—289 cm
runoff_mm = runoff_surface_mm + runoff_subsurface_mm
balance_mm = p_mm - et_loss_mm - runoff_mm
```

### 4.3 GLDAS-2.1 Noah 字段映射

| 原生变量名 | 项目规范字段 | 单位／转换 | 用途 |
|---|---|---|---|
| `SoilMoi0_10cm_inst` | `sm_0_10_mm` | kg/m² 在水量意义上按 mm | 0—10 cm |
| `SoilMoi10_40cm_inst` | `sm_10_40_mm` | 同上 | 10—40 cm |
| `SoilMoi40_100cm_inst` | `sm_40_100_mm` | 同上 | 40—100 cm |
| `SoilMoi100_200cm_inst` | `sm_deep_mm` | 同上 | 100—200 cm 深层状态 |
| M1 元数据核验后的降水字段 | `p_mm` | 速率／累计类型核验后转为候 mm | P、P95、F_R |
| M1 元数据核验后的蒸散字段 | `et_loss_mm` | 符号与累计类型核验 | B |
| M1 元数据核验后的地表径流字段 | `runoff_surface_mm` | 水量单位核验 | R |
| M1 元数据核验后的地下径流字段 | `runoff_subsurface_mm` | 水量单位核验 | R |

v1.3.1 未冻结 GLDAS 降水、ET 和径流的具体原生字符串，因此不得在代码中凭经验写死；必须在 M1 的 `source_variable_map` 中由官方元数据确认后才能运行 M2。派生：

```text
sm_0_100_mm = sm_0_10_mm + sm_10_40_mm + sm_40_100_mm
runoff_mm = runoff_surface_mm + runoff_subsurface_mm
balance_mm = p_mm - et_loss_mm - runoff_mm
```

ERA5-Land 与 GLDAS 的 `sm_deep_mm` 层深不同，只比较同产品内部百分位、标准化距平和效应方向，不比较绝对 mm 优劣。

### 4.4 CHIRPS 字段映射

| 原生语义 | 项目规范字段 | 处理 |
|---|---|---|
| `precipitation` | `p_mm_day` | 原生 QC 和完整性审计后保留日 mm |
| 派生候总量 | `p_mm` | 完整日记录求和；第73候保留5／6天实际总量 |
| 派生日速率 | `p_mm_per_day` | `p_mm/n_days`，仅用于第73候敏感性 |

CHIRPS 必须独立计算自身 P95，不使用 ERA5-Land 或 GLDAS 阈值；融合站点使其只能承担一致性检查，不能自动称完全独立验证。

### 4.5 LAI、NDVI、物候和地类字段映射

| 产品 | 原生字段 | 项目规范字段 | 冻结规则 |
|---|---|---|---|
| MCD15A3H.061 | `Lai_500m` | `lai_native` | 乘比例因子 0.1；缺测不得当 0 |
| MCD15A3H.061 | `FparLai_QC` | `lai_qc_main` | 原生位解码：MODLAND_QC、传感器、云状态、SCF_QC |
| MCD15A3H.061 | `FparExtra_QC` | `lai_qc_extra` | 原生排除雪冰、高／中气溶胶、卷云、内部云、云阴影等 |
| MOD13Q1.061 | `NDVI` | `ndvi_native` | 乘比例因子 0.0001 |
| MOD13Q1.061 | pixel reliability | `ndvi_reliability` | 主保留 0／1；严格仅 0 敏感性 |
| MOD13Q1.061 | VI Quality | `ndvi_vi_quality` | 原生位解码；具体位定义以随版本元数据登记 |
| MCD12Q2.061 | `Greenup` | `greenup_native` | 多有效周期取区间并集 |
| MCD12Q2.061 | `Dormancy` | `dormancy_native` | 与 Greenup 共同构成活跃窗 |
| MCD12Q2.061 | `NumCycles` | `num_cycles` | 周期完整性审计 |
| MCD12Q2.061 | `EVI_Amplitude` | `evi_amplitude` | 单周期展示时按冻结 tie-break 使用 |
| MCD12Q2.061 | `QA_Overall` | `phenology_qa_overall` | 主保留 Best／Good |
| MCD12Q2.061 | `QA_Detailed` | `phenology_qa_detailed` | 原生 QA 审计 |
| MCD12Q1.061 | `LC_Type1` | `igbp_code` | 分类面积比例，不插值类别编号 |
| MCD12Q1.061 | 随产品 QC 字段 | `landcover_qc` | M1 核验官方字段后登记 |

MOD13Q1 的可靠性／质量字段具体原生字符串若在下载元数据中与上述语义名不同，以官方元数据为准，在 `source_variable_map` 中建立映射；不得改变冻结的 0／1 保留规则。

### 4.6 静态协变量字段映射

| 数据源 | 项目规范字段 | 含义 | 处理要求 |
|---|---|---|---|
| SoilGrids250m | `sand_0_30_source` | 0—30 cm 砂粒原始值 | 原生单位、比例因子和版本由 M1 登记 |
| SoilGrids250m | `clay_0_30_source` | 0—30 cm 黏粒原始值 | 同上 |
| SoilGrids250m | `sand_0_30` | 单位审计后的砂粒含量 | 面积聚合到网格，模型前标准化 |
| SoilGrids250m | `clay_0_30` | 单位审计后的黏粒含量 | 同上 |
| NASADEM_HGT.001 | `elevation_m` | 高程 | 原生单位与无效值核验后面积聚合 |
| NASADEM_HGT.001 | `slope_deg` | 由高程派生坡度 | 保存算法、CRS 和代码版本 |
| MCD12Q1.061 | `land_cover` | 基线地类：forest／grassland／cropland／other | 仅作协变量和分层，不动态硬删事件 |
| ERA5-Land | `annual_p_mean_mm` | 2000—2023 年均降水 | 固定气候背景协变量 |
| ERA5-Land | `apr_sep_t2m_mean_c` | 2000—2023 年4—9月均温 | 固定气候背景协变量 |

### 4.7 可选环流与站点字段

- 环流规范字段：`z500`、`u700`、`v700`、`q700`、`u850`、`v850`、`q850`、`ivt`；实际原生变量、单位、压力层和 IVT 计算字段在下载后冻结。
- 土壤水站规范字段：`station_id`、`lon`、`lat`、`timestamp_local`、`timezone`、`depth_top_cm`、`depth_bottom_cm`、`sm_value`、`sm_unit`、`qc_flag`。
- 降水站规范字段：`station_id`、`lon`、`lat`、`timestamp_local`、`timezone`、`p_value`、`p_unit`、`qc_flag`、`independent_holdout_flag`。
- 站点清单、使用权、层深和时制未验收前，不得把相似站点或 CHIRPS 融合关系冒充独立验证。

## 5. 全局参数文件规范

### 5.1 参数文件组织原则

`params.yaml` 至少包含以下顶级键：

```text
protocol
grid
time
spatial
mask
phenology
clim
drought
recovery
pterm
fr
fz
lag
dfai
lai
ndvi
deep
covariates
route1
route2
infer
trend
block
equivalence
psm
spec_curve
products
random
output
```

科学参数只能从本文件读取。代码可以对参数做类型和范围断言，但不得提供另一套默认值覆盖本文件。

### 5.2 网格、时间与空间支撑

| 参数键 | 主值 | 敏感性／说明 |
|---|---|---|
| `grid.resolution_deg` | 0.1 | GLDAS 原生复算为 0.25 |
| `grid.main_version` | `era5land_010` | 主网格 |
| `time.year_start` | 2000 | 总体事件起点 |
| `time.year_end` | 2023 | 全产品共同止点 |
| `time.pentads_per_year` | 73 | 第1—72候5天，第73候5／6天 |
| `time.state_min_valid_days` | 4 | 候状态均值最低有效日数 |
| `time.state_max_consecutive_missing_days` | 2 | 超过则候状态缺失 |
| `time.flux_requires_complete_days` | true | 候通量必须日记录完整 |
| `spatial.valid_area_min` | 0.70 | 0.50／0.85 |
| `spatial.gldas_regrid` | `conservative_area` | 最近邻状态量为敏感性；不得声称增加信息 |
| `spatial.gldas_native_rerun` | true | 原生0.25°全链复算 |

### 5.3 静态掩膜与物候

| 参数键 | 主值 | 敏感性／失败处置 |
|---|---|---|
| `mask.igbp_keep` | `[1,2,3,4,5,6,7,8,9,10,12,14]` | 排除11、13、15、16、17 |
| `mask.valid_year_start/end` | 2001／2023 | 静态判定序列 |
| `mask.valid_years_min` | 10 | 不足则不参与静态判定 |
| `mask.native_exclude_frac` | 0.80 | 达到则原生像元永久排除 |
| `mask.veg_area_min` | 0.50 | 0.30／0.70 |
| `mask.baseline_years` | 2001—2005 | 基线类别掩膜敏感性 |
| `phenology.qa` | `[Best,Good]` | Best-only、纳入 Fair |
| `phenology.pixel_area_min` | 0.50 | 0.30／0.70 |
| `phenology.native_pixels_min` | 30 | 当年窗最低有效原生像元数 |
| `phenology.valid_years_min` | 5 | 低于则格点主分析缺失 |
| `phenology.multicycle` | `union` | 单周期仅作展示／敏感性 |
| `phenology.single_cycle_tie_days` | 5 | 与4—9月重叠差≤5天时取 EVI_Amplitude 较大者 |
| `phenology.fallback` | `grid_median_sos_eos` | 当年无效及2000年使用并标记 |
| `phenology.fixed_window` | 4—9月 | 仅敏感性；事件资格、L、植被年合成同步切换 |

### 5.4 气候态与第73候

| 参数键 | 主值 | 说明 |
|---|---|---|
| `clim.base_window` | 2000—2023 | 固定基准，各产品独立计算 |
| `clim.pentad_pool` | `[-1,0,+1]` | 同日历程候±1；沿连续时间轴跨年 |
| `clim.min_n` | 40 | 低于则该格点—候缺失 |
| `clim.gringorten_a` | 0.44 | `p=(r-a)/(n+0.12)` |
| `clim.gringorten_b` | 0.12 | 并列取平均秩 |
| `clim.smp_multiplier` | 100 | `SMP=100p` |
| `clim.normal_p_eps` | 0.000001 | W 的 p 端点截断到 `[eps,1-eps]` |
| `clim.balance_formula` | `P-ET_loss-R` | R=地表＋地下径流 |
| `clim.p95_include_zero` | true | 含零样本线性分位 |
| `clim.p95_min_nonzero_n` | 20 | 低于则 R 分支不可用 |
| `clim.p95_zero_unusable` | true | P95=0 时 R 分支不可用 |
| `clim.pentad73_checks` | `[daily_rate,five_day_equivalent,drop_pentad73]` | 另分别检查平年／闰年超标率 |

### 5.5 骤旱识别与恢复

| 参数键 | 主值 | 说明 |
|---|---|---|
| `drought.smp_above` | 40 | 最近参照候须 >40% |
| `drought.smp_below` | 20 | 事件最低值须 <20% |
| `drought.drop_rate_pct_per_pentad` | 5 | 最近>40%候至 t_min 的平均下降速率下限 |
| `drought.min_duration_pentads` | 4 | 主定义为总持续≥4候 |
| `drought.development_duration_sensitivity` | 截至 t_min 连续至少4候 SMP<40% | 单独建库，不与主库拼接 |
| `drought.tie_t_min` | `first` | 并列最低取首次 |
| `drought.gap_breaks_segment` | true | 不跨 SMP 缺口连接 |
| `recovery.terminate_smp` | 20 | 最低点后首次 >20% |
| `recovery.terminate_smp_sensitivity` | 40 | 完整重跑，不拼接 |
| `recovery.rt_formula` | `t_e-t_min` | 单位候 |
| `recovery.delta_formula` | `SMP(t_e)-SMP(t_min)` | 单位百分位 |
| `recovery.rr_formula` | `delta_SMP/RT` | 单位百分位／候 |
| `recovery.early_pentads` | 2 | 最低点后早期恢复速率补充指标 |
| `recovery.post_te_trajectory` | `[1,2,3,4,5]` | t_e 后轨迹补充 |

### 5.6 P-term、F_R、F_Z、Lag 与 DFAI

| 参数键 | 主值 | 敏感性／约束 |
|---|---|---|
| `pterm.window` | `[t_min,t_e+2]` | `[t_min,t_e+1]` |
| `pterm.percentile` | 95 | P99、湿候 P95、原 R95p |
| `pterm.min_p_mm` | 1 | 实际降水须严格 >1 mm |
| `fr.window` | `[t_e-1,t_e+1]` | ±2候 |
| `fr.percentile` | 95 | 与 P-term 各自按方案计算 |
| `fr.min_p_mm` | 1 | 严格 >1 mm |
| `fr.subtypes` | `[pre,sync,post]` | 按首个 t_w 与 t_e 的关系 |
| `fr.h1_uses` | `[pre,sync]` | post 不进入非 F_R 对照 |
| `fz.window` | `[t_e-1,t_e+1]` | ±2候 |
| `fz.w1_rule` | `<0` | 固定 |
| `fz.w2_threshold` | 0.5 | 0.84／1.28；不称95%极端 |
| `lag.lag_p` | `t_P95-t_min` | 仅 P-term 阳性 |
| `lag.lag_fr` | `t_w_R-t_min` | 仅 F_R 阳性 |
| `lag.offset_fr` | `t_w_R-t_e` | 仅 F_R 阳性 |
| `dfai.alpha` | 3.2 | 2.0／4.1；不是本地物理常数 |
| `dfai.strict_domain` | `W1<0 and W2>0` | 仅 E2a；发生样本不因此删除 |
| `wet_process.allow_one_gap` | false | true 为敏感性 |

### 5.7 LAI、NDVI 与深层水

| 参数键 | 主值 | 敏感性／约束 |
|---|---|---|
| `lai.scale_factor` | 0.1 | 原生值乘法 |
| `lai.window_years` | 5 | 3／10年；不同窗不得混作同一暴露 |
| `lai.window_offset` | `y-5...y-1` | 不使用事件年或事件后 |
| `lai.main_requires_full` | 5 | 5/5有效；4/5敏感性 |
| `lai.annual_time_cover_min` | 0.70 | 0.50／0.85 |
| `lai.annual_space_cover_min` | 0.70 | 0.50／0.85 |
| `lai.base_method` | `mean_of_growing_season_annual_values` | 五年生长季 LAI 均值 |
| `lai.trend_method` | `theil_sen` | 单位 LAI／年；连续变量使用 |
| `lai.standardization` | `sample_1sd` | 同时保留原单位 |
| `lai.no_future_fill` | true | 禁止后值回填 |
| `ndvi.scale_factor` | 0.0001 | 原生值乘法 |
| `ndvi.reliability_keep` | `[0,1]` | 严格仅0敏感性 |
| `ndvi.common_sample_years` | 2008—2023 | 与 LAI 同事件、同窗口、同掩膜 |
| `deep.pre_pentads` | 4 | 前1／12候 |
| `deep.era5_depth_cm` | `[100,289]` | 第4层 |
| `deep.gldas_depth_cm` | `[100,200]` | 不与 ERA5 绝对量比较 |
| `deep.summary` | `mean` | t_s−4至t_s−1平均后转同产品日历候百分位／标准化距平 |

### 5.8 路线一恢复风险与路线二

| 参数键 | 主值 | 说明 |
|---|---|---|
| `route1.recovery_risk_t0` | `t_min` | 从下一候评估首次恢复 |
| `route1.recovery_risk_h` | 12 | 6／18候敏感性 |
| `route1.recovery_time_df` | 3 | 受限三次样条；不足时线性时间项 |
| `route1.cross_season` | true | 季末不删失 |
| `route1.censor_types` | `[administrative,missing]` | 分开编码 |
| `route1.ipcw` | `sensitivity` | 缺失删失较多时探索性使用 |
| `route2.t0` | `t_s` | 与路线一恢复风险不同 |
| `route2.h` | 12 | 6／18候敏感性 |
| `route2.exits` | `[A,B,C]` | 删失不是第四出口 |
| `route2.time_df` | 3 | A／B原因别离散风险 |
| `route2.strict_post_reclass` | `B_to_A_strict` | 仅敏感性；主A／B不变 |

### 5.9 核心协变量与模型集合

冻结核心协变量键：

```text
annual_p_mean_mm
apr_sep_t2m_mean_c
sand_0_30
clay_0_30
elevation_m
slope_deg
land_cover
pentad_sin
pentad_cos
year_centered_2000
active_window_length_L
```

规则：

- 连续变量标准化；核心协变量缺失时，该模型完整案例排除，不作后值插补。
- 年份分类、土壤／地形精简为仅高程／黏粒是敏感性。
- 事件最低 SMP、发展速率和事件前短期气象仅属扩展调整集，可能是路径变量。
- 事件后 LAI、事件后 ET 和恢复期降水不得进入前因模型或倾向评分。
- 模型 L：`outcome ~ LAI_trend + LAI_base + core_covariates`。
- 模型 D：`outcome ~ deep_SM_pre4 + core_covariates`。
- 模型 I：`outcome ~ LAI_trend*deep_SM_pre4 + LAI_base + core_covariates`。
- 若 `|cor(LAI_base,LAI_trend)|>0.80`，另用分开模型，不联合解释两个系数。

### 5.10 推断、趋势、等价和路线二门槛

| 参数键 | 主值 | 说明 |
|---|---|---|
| `infer.epv_min` | 约10 | 每有效自由参数约10个对应结局 |
| `infer.min_n` | 30 | 事件级正式推断项目最低线 |
| `infer.min_event_per_arm` | 10 | 结局与非结局各至少10 |
| `infer.min_blocks` | 10 | 空间块最低数 |
| `infer.min_n_eff` | 20 | 达到后仍须满足 EPV |
| `infer.quantile_025_075_n` | 80 | 且 n_eff≥40 |
| `infer.design_effect_formula` | `n/[1+(m-1)rho]` | 加权另报 `(sum_w)^2/sum_w2` |
| `trend.min_valid_years` | 18 | 15／20敏感性 |
| `trend.year_min_events` | 10 | 年事件<10则该指标当年缺失 |
| `trend.autocorr_trigger` | `ljung_box_lag1_p<0.05` | 触发主报告 Hamed–Rao；始终修正作敏感性 |
| `block.km` | 100 | 50／200 km敏感性 |
| `block.bootstrap_n` | 500 | 主区间 |
| `block.two_way_cluster` | `[space,year]` | 并列报告，不一致取较宽区间 |
| `diagnostic.balance_residual_median_max` | 0.20 | 若展示归一化收支残差，超过则降级为诊断，不进入机制排序 |
| `equivalence.or` | `[1/1.20,1.20]` | 整个区间落入才称等价 |
| `equivalence.cont_sd` | 0.10 | 连续结局±0.10 SD |
| `psm.high_quantile` | 0.75 | 高组≥Q75 |
| `psm.low_quantile` | 0.25 | 低组≤Q25 |
| `psm.estimand` | `ATT_high` | 1:1最近邻 |
| `psm.caliper` | 0.05 | logit倾向评分 |
| `psm.max_abs_smd` | 0.10 | 未达标按预设降级 |
| `gam.max_edf` | 3 | n_eff<50线性；50≤n_eff<100仅参考线 |
| `spec_curve.r_robust` | 0.80 | 另检查主要定义族是否反向 |
| `route2.multi_n` | 200 | 且A／B／C各≥30、块≥20、EPV合格 |
| `route2.interval_n_eff` | 100 | 且单一块不超过20%的B |
| `route2.exit_b_min` | 30 | B<30触发退出主模型 |
| `route2.exit_blocks_min` | 10 | 有效块<10触发退出主模型 |
| `null_model.circular_shifts` | 1000 | 排除0位移；经验p分母1001 |
| `multiple_testing.family_alpha` | 0.05 | Q1／Q2／Q3各自 Holm |
| `multiple_testing.map_bh_q` | 0.05 | 探索性格点地图 |

## 6. 核心交接表与 Schema

### 6.1 通用字段约定

所有冻结科学表至少携带或通过 `run_manifest` 可解析到：

```text
protocol_version, run_id, params_hash, code_hash, source_manifest_hash,
grid_version, support_id, phenology_mode, created_at, schema_version
```

其中 `created_at` 仅用于审计，不参与科学结果哈希。大表可将重复版本字段放在分区元数据，但必须能无歧义关联到唯一运行。

### 6.2 `source_file_manifest`：原始文件清单

**一行一个原始文件；主键 `file_id`。**

| 字段 | 含义 |
|---|---|
| `file_id` | 文件唯一ID |
| `product_code`、`collection_version` | 产品与集合版本 |
| `native_variable_names` | 文件包含的原生变量列表 |
| `time_start`、`time_end` | 原生覆盖时间 |
| `download_date`、`request_id`、`source_url` | 获取审计 |
| `file_path`、`file_size_bytes`、`sha256` | 文件定位与校验 |
| `spatial_extent`、`native_resolution` | 空间元数据 |
| `crs`、`lat_direction`、`lon_direction` | 坐标审计 |
| `time_zone`、`timestamp_meaning` | 时间戳含义 |
| `accumulation_type` | `increment`、`processing_step_accumulation`、`interval_total`、`instantaneous`、`unknown` |
| `unit_source`、`scale_factor`、`add_offset`、`fill_value` | 单位与编码 |
| `license`、`access_status` | 使用权 |
| `audit_status`、`audit_note` | 是否可进入主链 |

### 6.3 `source_variable_map`：原生—规范变量映射

**主键 `mapping_id`；唯一约束 `product_code+collection_version+native_variable_name+canonical_field`。**

```text
mapping_id, product_code, collection_version, native_variable_name,
canonical_field, native_unit, canonical_unit, scale_factor, add_offset,
sign_rule, accumulation_type, qc_fields, metadata_source, verified_by,
verification_date, mapping_status, note
```

`mapping_status=unknown` 的土壤水、降水、ET、径流和累计字段不得进入 M2 主链。

### 6.4 `time_pentad_calendar`：73候日历

**主键 `t_abs`。**

```text
t_abs, year, pentad, start_date, end_date, n_days, is_leap_year,
is_pentad73, previous_t_abs, next_t_abs
```

验收：每年73候；日期连续无重叠无空洞；平年第73候5天、闰年6天；次年第1候与当年第73候连续。

### 6.5 `grid_manifest`：网格与空间块

**主键 `grid_version+grid_id`。**

```text
grid_version, grid_id, lon, lat, area_km2, boundary_include,
block_id, superblock_id, native_gldas_grid_id, grid_geometry_id,
valid_area_fraction, grid_qc_status
```

`superblock_id` 可在 M5 湿过程和区域 cluster 连接后生成新版；不得覆盖早期版本，须保存 `superblock_version` 和成员关系表。

### 6.6 `grid_day`：格点—日基础表

**主键 `product_code+grid_version+grid_id+date+support_id`。**

```text
product_code, grid_version, grid_id, date, support_id,
sm_0_100_mm, sm_deep_mm, p_mm, et_loss_mm, pet_loss_mm,
runoff_surface_mm, runoff_subsurface_mm, runoff_mm, balance_mm,
t2m_c, valid_native_area_frac, qc_status, missing_reason
```

不要求所有产品都有所有字段；不适用为空并由产品字典说明。该表是中间交接表，不能直接当作 SMP 或事件结局表。

### 6.7 `grid_pentad_base`：候尺度物理量

**主键 `product_code+grid_version+grid_id+t_abs+support_id`。**

```text
product_code, grid_version, grid_id, t_abs, year, pentad, support_id,
start_date, end_date, n_days, sm_0_100_mm, sm_deep_mm, p_mm,
p_mm_per_day, p_5day_equivalent_mm, et_loss_mm, pet_loss_mm,
runoff_surface_mm, runoff_subsurface_mm, runoff_mm, balance_mm,
t2m_c, state_valid_days, state_max_consecutive_missing_days,
flux_complete_flag, valid_native_area_frac, qc_status, missing_reason
```

### 6.8 `grid_mask`：静态掩膜与基线地类

**主键 `grid_version+grid_id+mask_version`。**

```text
grid_version, grid_id, mask_version, valid_landcover_years,
native_exclude_frac, vegetation_area_frac, mask_include,
baseline_land_cover, land_cover, exclusion_reason,
baseline_mask_flag, no_landcover_mask_flag
```

### 6.9 `grid_phenology_year`：逐年物候窗与回退

**主键 `grid_version+grid_id+year+phenology_mode`。**

```text
grid_version, grid_id, year, phenology_mode, cycle_id,
greenup_date, dormancy_date, greenup_doy, dormancy_doy,
num_cycles, evi_amplitude, qa_overall, qa_detailed,
valid_pixel_area_frac, valid_native_pixels, valid_phenology_years,
phenology_fallback, active_window_start, active_window_end,
phenology_qc_status, exclusion_reason
```

多周期并集需另用 `grid_phenology_segment` 一行一区间保存，不能把多个起止日期挤入一个字符串后失去结构。

### 6.10 `grid_active_pentad`：活跃窗长表

**主键 `grid_version+grid_id+t_abs+phenology_mode`。**

```text
grid_version, grid_id, t_abs, year, pentad, phenology_mode,
active_flag, active_window_id, phenology_fallback,
active_window_length_L, selection_sensitivity_group
```

### 6.11 `grid_climatology`：逐产品气候态与阈值

**主键 `product_code+grid_version+grid_id+pentad+clim_version`。**

```text
product_code, grid_version, grid_id, pentad, clim_version,
clim_start_year, clim_end_year, pool_offset, sm_n, balance_n,
p_n, p_nonzero_n, p_zero_fraction, p95_mm, p99_mm,
wet_p95_mm, p95_usable, sm_distribution_id, balance_distribution_id,
pentad73_check_status, climatology_qc_status
```

实际逐年分布可保存在 Parquet 分区或分布对象中；无论采用何种存储，必须能重建每次 Gringorten 秩转换。

### 6.12 `grid_pentad`：M3 下游统一接口

**主键 `product_combo+grid_version+grid_id+t_abs+support_id+phenology_mode+clim_version`。**

```text
product_combo, soil_product, precip_product, grid_version, grid_id,
t_abs, year, pentad, start_date, end_date, n_days, support_id,
phenology_mode, clim_version, active_flag, active_window_length_L,
phenology_fallback, sm_0_100_mm, smp, sm_rank_n, p_mm,
p_mm_per_day, p_5day_equivalent_mm, p95_mm, p95_n, p_nonzero_n,
p95_usable, et_loss_mm, runoff_mm, balance_mm, balance_rank_n,
balance_p, w, sm_deep_mm, valid_native_area_frac, qc_status,
missing_reason
```

`p95_usable=0` 不等于无降水；只表示 R 分支在该格点—候不可用。

### 6.13 `event_master`：格点事件主表

**一行一个 `episode_id`；主键 `episode_id`。** 由 M4 建立事件与删失骨架，M5 生成恢复和急转字段的新版本。暴露不通过回写加入；M6 后由兼容性视图连接。

| 字段 | 类型／单位 | 定义与缺失规则 |
|---|---|---|
| `episode_id` | string | 稳定事件ID |
| `grid_id`、`cluster_id` | string | 格点事件与区域事件分别标识 |
| `product` | string | 四类产品组合ID |
| `soil_product`、`precip_product` | string | 数据源分解 |
| `grid_version`、`support_id` | string | 网格与样本支撑 |
| `duration_definition`、`termination_rule` | string | 主定义或敏感性定义 |
| `phenology_mode` | string | 动态／固定／气候态等 |
| `year` | integer | 事件起始年，即 `year(t_s)` |
| `t_s`、`t_min`、`t_e` | integer t_abs | 起始、首次最低、终止；未恢复时 t_e 为空 |
| `t_s_year/pentad` 等 | integer | 三个人类可读时间锚点 |
| `right_censored` | 0/1 | 到数据末端或规定随访仍未终止者保留 |
| `censor_type` | enum | `none`、`data_end`、`missing_smp`、`administrative` 等 |
| `censor_t_abs` | integer | 最后有效或行政删失位置 |
| `duration` | 候 | 主事件持续长度；未终止时不用虚构 t_e 计算 |
| `observed_duration` | 候 | 可用于删失事件审计的已观察长度 |
| `development_rate` | 百分位／候 | 最近>40%候至 t_min 的平均下降速率 |
| `smp_min` | 百分位 | 事件最低 SMP |
| `mean_deficit`、`max_deficit` | 百分位 | 事件期平均／最大亏缺 |
| `RT` | 候 | 仅已恢复事件；`t_e-t_min` |
| `delta_SMP` | 百分位 | 仅已恢复事件 |
| `RR` | 百分位／候 | 仅已恢复且 RT>0 |
| `recovery_slope` | 百分位／候 | 恢复段 Theil–Sen 斜率 |
| `early_recovery_rate` | 百分位／候 | 最低点后前2候补充指标 |
| `route1_A_eligible` | 0/1 | t_s、t_e 均在活跃窗且已恢复 |
| `recovery_risk_eligible` | 0/1 | t_s、t_min 在活跃窗；不要求未来 t_e 在活跃窗 |
| `P_term` | 0/1/NA | 主窗是否有合格降水；窗口不完整为NA |
| `P_term_status` | enum | `positive`、`negative`、`window_incomplete`、`r_unusable` 等 |
| `t_P95` | integer/NA | 首个 P-term 合格候 |
| `Lag_P` | 候/NA | 仅 P-term=1 |
| `F_R` | 0/1/NA | 主急转结局；窗口不完整不得为0 |
| `F_R_status` | enum | 完整、未知或不可用原因 |
| `F_R_subtype` | enum/NA | `pre`、`sync`、`post`；非F_R为空 |
| `t_w_R` | integer/NA | 首个F_R合格候 |
| `Lag_FR` | 候/NA | 仅F_R=1 |
| `Offset_FR` | 候/NA | 仅F_R=1 |
| `F_Z` | 0/1/NA | 补充急转结局 |
| `F_Z_status` | enum/NA | 窗口和W可用性 |
| `wet_process_id` | string/NA | 共享湿过程标记 |
| `phenology_fallback` | 0/1 | 当年是否使用回退物候 |
| `active_window` | string | 活跃窗ID或结构化引用 |
| `land_cover` | enum | forest／grassland／cropland／other |
| `data_completeness` | number | 关键段完整度；口径见数据字典 |
| `missingness_flags` | JSON/结构化数组 | 不用自由文本替代机器可读原因 |

M6 后提供只读兼容视图 `event_master_v1_3_1`，在以上字段基础上连接：

```text
LAI_base, LAI_trend, LAI_exposure_cluster,
NDVI_base, NDVI_trend, deep_SM_pre4, shallow_SM_pre4
```

该视图必须由 `event_master+event_exposure` 自动生成，不允许单独手填，也不得以视图替代规范化暴露长表。

### 6.14 `event_candidate_audit`：候选事件与排除原因

**主键 `candidate_id`。**

```text
candidate_id, product, grid_id, t_s_candidate, t_min_candidate,
t_e_candidate, smp_above_anchor, smp_min, development_rate,
duration_observed, continuity_ok, active_window_ok,
eligible_main, exclusion_reason, code_version
```

候选失败也须留痕，但不得把每一个普通非干旱格点—候都膨胀成候选行；候选入口由连续<40%片段定义。

### 6.15 `event_precip`：全部合格降水候长表

**主键 `episode_id+t_abs+p_term_definition`。**

```text
episode_id, t_abs, year, pentad, p_mm, p95_mm, p99_mm,
p_mm_per_day, p_5day_equivalent_mm, p95_qualify, p99_qualify,
in_pterm_window, in_fr_window, is_first_pterm, is_first_fr,
pentad73_flag, precip_qc_status
```

必须保存窗口内全部合格降水候，而不是只保存首个日期。

### 6.16 `event_branch`：分支强度表

**一行一个 `episode_id×branch`；主键 `episode_id+branch+branch_definition`。**

```text
episode_id, branch, branch_definition, t_w, W1, W2,
DFAI_alpha, DFAI, E2a_eligible, wet_process_id,
window_status, branch_available, missing_reason
```

- `branch` 取 `R` 或 `Z`。
- 非 FD-WT 的 A 不强造 `t_w`；没有该分支阳性结果时不在本表造空行，发生与窗口状态统一由 `event_master` 承载。
- 交集事件可有 R、Z 两行，各自保留自己的 t_w。
- 总体 FD-WT 计数按 `R∪Z` 对 episode 去重，不把两行相加。

### 6.17 `event_recovery_trajectory`：恢复过程表

**主键 `episode_id+t_abs`。**

```text
episode_id, t_abs, relative_to_tmin, relative_to_te,
smp, recovery_phase_flag, early_recovery_flag, post_te_flag,
active_flag, qc_status
```

至少覆盖恢复段、最低点后前2候和 t_e 后1—5候；路线一恢复风险另用专门事件—候表，不能靠本表隐式推断删失。

### 6.18 `route1_recovery_person_pentad`：路线一恢复风险表

**一行一个 `episode_id×followup_pentad`；主键 `episode_id+followup_pentad`。**

```text
episode_id, t0_tmin, followup_pentad, t_abs, at_risk,
recovery_event, censor_administrative, censor_missing,
censor_data_end, censor_reason, last_valid_t_abs,
smp, active_flag, exposure_version, analysis_weight
```

构造断言：

- 入组要求 `recovery_risk_eligible=1`；t0=t_min，从下一候开始。
- 主 H=12；可跨活跃窗，季末不删失。
- 首次 SMP>20% 时 `recovery_event=1`，随后退出风险集。
- SMP 缺口导致状态不可知时，在最后连续有效候删失，不在缺口后重新入组。
- 到 H 或2023年数据末端仍未恢复分别编码行政原因。
- 仅行政删失完整随访子样本和 IPCW 是敏感性，不覆盖主表。

### 6.19 `vegetation_grid_year`：LAI／NDVI 年合成表

**主键 `grid_id+year+vegetation_product+phenology_mode+mask_version+qc_version`。**

```text
grid_id, year, vegetation_product, phenology_mode, mask_version,
qc_version, vegetation_annual_mean, active_pentad_n,
valid_pentad_n, temporal_coverage, native_valid_area,
total_native_area, spatial_coverage, annual_valid,
strict_qc_flag, exclusion_reason
```

LAI 年值由合格4天观测按与候重叠天数加权到候，再对活跃窗内有效候平均；NDVI 使用相同活跃窗和完整性规则。年值无效时 `vegetation_annual_mean` 为空，不得填0。

### 6.20 `event_exposure`：事件暴露长表

**一行一个 `episode_id×exposure_version`；主键 `episode_id+exposure_version`。**

```text
episode_id, exposure_version, grid_id, year,
window_start_year, window_end_year, window_years,
LAI_base, LAI_trend, LAI_n_valid_years, LAI_full_window,
LAI_exposure_cluster, LAI_missing_reason,
NDVI_base, NDVI_trend, NDVI_n_valid_years, NDVI_missing_reason,
deep_SM_pre4, deep_SM_pre4_percentile, deep_SM_pre4_z,
deep_window_start_tabs, deep_window_end_tabs, deep_missing_reason,
shallow_SM_pre4, shallow_SM_pre4_percentile,
annual_p_mean_mm, apr_sep_t2m_mean_c, sand_0_30, clay_0_30,
elevation_m, slope_deg, land_cover, pentad_sin, pentad_cos,
year_centered_2000, active_window_length_L,
exposure_complete_L, exposure_complete_D, exposure_complete_I,
core_covariate_missing_reason
```

时间断言：

- 五年植被窗必须为 `year-5...year-1`，且所有年合成只使用事件前完整年。
- 深层主窗必须为 `t_s-4...t_s-1`。
- 不允许事件年 LAI、事件后 LAI、事件后 ET 或恢复期降水进入该表的前因字段。
- `exposure_complete_L/D/I` 分别按对应模型完整案例规则生成，不得用一个共同删除规则缩掉其他模型。

### 6.21 `exposure_cluster_audit`：LAI 暴露簇审计

**主键 `analysis_id+LAI_exposure_cluster`。**

```text
analysis_id, LAI_exposure_cluster, grid_id, year, n_event,
cluster_event_fraction, selected_event_seed_id,
selected_episode_id, inverse_cluster_weight,
block_id, superblock_id
```

配套 `exposure_cluster_summary` 一行一个 `analysis_id`：

```text
analysis_id, n_event, n_exposure, cluster_size_median,
cluster_size_max, cluster_size_p95, max_cluster_contribution,
epv_event_basis, epv_exposure_basis, n_eff_event_basis,
n_eff_exposure_basis, conservative_epv, conservative_n_eff
```

模型 L 的正式支撑取事件、暴露簇和空间块口径中更保守者；模型 I 虽含事件级深层水，也须报告同一审计。

### 6.22 `grid_year`：格点—年汇总表

**主键 `product+definition_id+grid_id+year+support_id+phenology_mode`。**

```text
product, definition_id, grid_id, year, support_id, phenology_mode,
L, N_onset, N_A, N_FR, N_FZ, N_censored, affected_area,
phenology_fallback_rate, LAI_availability, block_id,
annual_p_mean_mm, apr_sep_t2m_mean_c, data_completeness
```

- L 为活跃候数；E1a 仅在 L>0 时进入，offset=`log(L)`。
- E1b 仅在 N_A>0 时进入，为 `N_FR/N_A` 的条件比例。
- 影响面积按实际格点面积去重，不能由格点事件数直接代替。

### 6.23 `event_regional` 与 `event_regional_member`

`event_regional` 一行一个区域 `cluster_id`：

```text
cluster_id, product, definition_id, start_t_abs, end_t_abs,
n_grid_episodes, footprint_area_km2, footprint_geometry_id,
initial_footprint_cells, regional_qc_status
```

`event_regional_member` 主键 `cluster_id+episode_id+t_abs`：

```text
cluster_id, episode_id, t_abs, grid_id, cell_area_km2,
connected_flag, footprint_flag
```

同候4邻域连通，相邻候存在空间重叠或4邻域连接时链接；初始 footprint 至少3个0.1°格点。区域事件数与格点事件数不得相加。

### 6.24 `route2_person_pentad`：路线二事件—候表

**主键 `episode_id+followup_pentad`。**

```text
episode_id, t0_ts, followup_pentad, t_abs, at_risk,
exit_A, exit_B, exit_C_at_H, censored, censor_reason,
exit_type_unknown, extreme_without_recovery,
smp_tv, p95_flag_tv, recovery_this_pentad,
fr_type_known, F_R_subtype, first_exit_t_abs
```

原 v1.3.1 文档中的 `time-varying SMP` 和 `time-varying P95_flag` 在程序字段中分别规范为 `smp_tv` 与 `p95_flag_tv`，语义不变。

构造断言：

- t0=t_s，H=12；全部合格事件进入，不只保留已恢复事件。
- 每候先判断首次恢复；恢复且满足主 F_R 为 B，恢复但不满足为 A。
- B 分类需要 t_e+1；在 H 恢复时必须有 H+1 资料，否则急转类型未知，不归 A。
- 极端降水但未恢复者仍 `at_risk=1`，并令 `extreme_without_recovery=1`。
- 到 H 未恢复才 `exit_C_at_H=1`；删失另列，不是第四出口。
- A／B 为首次到达的吸收出口；恢复后新降水不改首次出口。
- 季末不删失；新一次骤旱另建 episode。

### 6.25 `route2_exit`：事件级出口汇总

**主键 `episode_id+route2_version`。**

```text
episode_id, route2_version, H, exit_type, exit_time,
censored, censor_time, censor_reason, exit_type_unknown,
exit_A_strict, strict_reclass_from_B, extreme_without_recovery_ever,
followup_complete, exposure_version
```

`exit_type` 仅取 `A`、`B`、`C`、`censored`、`unknown_type`；主出口和 `A_strict` 敏感性分列，禁止创造第四科学出口。

### 6.26 模型与规范结果表

`model_fit_manifest` 一行一个拟合：

```text
analysis_id, run_id, estimand, question, model_family, model_code,
outcome, exposure_version, definition_id, product, support_id,
sample_start_year, sample_end_year, formula, link_function,
n_event, n_exposure, n_outcome, n_nonoutcome, n_block,
n_superblock, n_eff, epv, conservative_epv, convergence_status,
separation_flag, support_gate, inference_level, model_object_path,
random_seed_id, code_hash
```

`model_result` 一行一个 `analysis_id+term`：

```text
analysis_id, term, scale, estimate, std_error, ci_low, ci_high,
ci_method, p_raw, test_family, p_holm, effect_unit,
reference_level, standardization, estimand_note
```

`model_marginal` 一行一个边际预测组合：

```text
analysis_id, term, deep_reference, deep_reference_value,
LAI_reference, LAI_reference_value, predicted_probability,
probability_difference, risk_difference, marginal_effect,
ci_low, ci_high, ci_method, scale
```

Q3 至少在深层水 P25／P50／P75 输出 LAI 边际效应、预测恢复／F_R 概率、概率差／风险差及区间；link 尺度乘积项和边际量尺不得互相替代。

### 6.27 审计与偏离表

`sample_flow` 一行一个分析步骤：

```text
analysis_id, step_order, module, step_name, n_before, n_after,
n_excluded, exclusion_reason, unit, product, definition_id,
support_id, exposure_version
```

`analysis_log` 一行一次模块运行：

```text
run_id, module, attempt_id, start_time, end_time, status,
params_hash, code_hash, input_file_hashes, output_file_hashes,
random_seed_id, n_input_rows, n_output_rows, sample_flow_path,
unit_test_status, warning_count, error_message
```

`deviation_log` 一行一个偏离：

```text
deviation_id, date, original_clause, new_clause, reason,
outcome_seen, affected_modules, approver, rerun_scope,
preregistered_or_posthoc, linked_run_id, status
```

未发生偏离时保留空表和表头，不得删除文件。

## 7. M0—M10 模块接口、冻结文件名与验收

### 7.1 模块接口总表

以下相对路径均以项目根目录为基准；`{run_id}` 由编排器替换。Parquet 可按产品／年份分区，但逻辑表名和字段不得改变。

| 模块 | 主责 | 必需输入 | 冻结输出文件 | 最低验收 |
|---|---|---|---|---|
| M0 协议冻结 | R1 | 五份v1.3.1文档、schema、研究区状态 | `config/params.yaml`；`metadata/protocol_freeze.json`；`logs/deviation_log.csv` | 科学口径无冲突；暂时锁定项明确 |
| M1 数据审计 | R2 | 原始文件与官方元数据 | `metadata/source_file_manifest.csv`；`source_variable_map.csv`；`logs/data_audit_log.jsonl` | 单位、累计类型、坐标、缺年和哈希留痕 |
| M2 预处理 | R2、R7 | M1及只读原生数据 | `time_pentad_calendar.parquet`；`grid_day_*.parquet`；`grid_pentad_base_*.parquet`；`grid_static_covariates.parquet` | 时间、符号、层厚和面积守恒测试通过 |
| M3 支撑与气候态 | R2、R4 | M2、MCD12Q1／Q2 | `grid_mask.parquet`；`grid_phenology_*.parquet`；`grid_active_pentad.parquet`；`grid_climatology_*.parquet`；`grid_pentad_*.parquet` | 各产品独立阈值；n≥40；回退与支撑可追踪 |
| M4 事件库 | R3 | M3 `grid_pentad` | `event_candidate_audit.parquet`；`event_master_base.parquet`；`event_regional*.parquet`；`event_manual_qc.csv` | 全部合格事件与右删失保留；随机≥30事件一致率100% |
| M5 恢复与急转 | R3 | M4、M3 P／W | `event_master.parquet`；`event_precip.parquet`；`event_branch.parquet`；`event_recovery_trajectory.parquet` | 时间锚点、未知窗口、分支去重和Lag样本正确 |
| M6 暴露连接 | R4、R7 | M4／M5、M3物候、LAI／NDVI、深层水 | `vegetation_grid_year_*.parquet`；`event_exposure.parquet`；`exposure_cluster_*.parquet` | 暴露严格早于t_s；五年窗和2008—2023样本正确 |
| M7 路线一模型 | R5 | M4—M6 | `route1_recovery_person_pentad.parquet`；`analysis_dataset_*.parquet`；`model_*.parquet`；`trend_result.parquet`；`sample_support.csv` | EPV、块数、n_eff、收敛、Holm和边际量尺齐全 |
| M8 路线二 | R3、R5 | M4／M5；可选M6 | `route2_person_pentad.parquet`；`route2_exit.parquet`；`route2_gate.json`；条件性模型输出 | 首次离场、H+1、删失和退出规则正确 |
| M9 稳健性 | R2、R3、R5、R7 | 多产品冻结运行、站点、规范矩阵 | `cross_product_*.parquet`；`station_validation_*.csv`；`spec_*.parquet` | 不共享阈值；匹配一对一；规范数与不适用规则完整 |
| M10 复核输出 | R6、R1 | 全部冻结表与日志 | `review_*.csv`；`sample_flow.csv`；`result_manifest.json`；最终图表与措辞审计 | 主表独立复算一致；偏离和缺失全登记 |

### 7.2 M0：协议、版本和 Schema 冻结

**输入**

- v1.3.1 五份文档；
- 本工程规格；
- 研究区矢量及其状态；
- 拟使用的代码版本、参数文件和空偏离日志。

**处理**

1. 将科学参数转换为机器可读 `params.yaml`，校验四层年份、两套时间零点和检验家族。
2. 注册所有表名、字段、类型、主键、受控词表和单位。
3. 计算参数哈希和文档哈希；固定随机种子 ID，但不查看暴露—结局效应。
4. 明确研究区矢量、站点和环流字段是否为暂时锁定；未验收项不能标为正式冻结。
5. 生成路线一与路线二分离的 DAG，以及四套产品组合和规范曲线配置骨架。

**冻结输出**

```text
config/params.yaml
config/schema_registry.yaml
config/specification_matrix.yaml
metadata/protocol_freeze.json
metadata/run_manifest.json
logs/{run_id}/deviation_log.csv
logs/{run_id}/module_status.csv
```

**验收与停止条件**

- 主结局、年份、阈值和角色冲突时停止；
- 研究区矢量未冻结时可以运行不包含空间结论的工程单元测试，不得生成正式区域结果；
- 第三方不可变时间戳登记前，状态只能写 `internal_preregistration_freeze`。

### 7.3 M1：原始数据、元数据和变量映射审计

**输入**：各产品只读原始文件、官方元数据、下载请求和站点使用信息。

**处理顺序**

1. 逐文件计算哈希、大小和空间范围，记录下载日期与请求编号。
2. 逐年逐月检查缺文件、重复时间、坐标翻转、纬度方向、异常常量、比例因子和填充值。
3. 登记原生字段、单位、时区、时间戳和累计类型。
4. 对 ERA5-Land 累计量用连续3天小时样例区分小时增量、处理步累计与已聚合区间总量。
5. 对 GLDAS 降水、ET、径流和 MODIS QC 的具体原生字段，依据官方元数据补齐映射，不凭经验猜测。
6. 建立站点原时制、层深、单位和独立／融合状态清单。

**冻结输出**

```text
metadata/source_file_manifest.csv
metadata/source_variable_map.csv
metadata/station_metadata.csv                 # 无站点时保留状态与空表
metadata/circulation_variable_map.csv         # 条件性
logs/{run_id}/data_audit_log.jsonl
outputs/{run_id}/reports/m1_data_coverage.csv
outputs/{run_id}/reports/m1_missing_files.csv
```

**失败退路**

- 缺年产品限定相应时段或退出对应分析，不插值伪造完整年；
- 累计类型、蒸发符号或关键字段映射不明时停止 M2 主链；
- 站点未落实不影响主分析，但站点验证措辞必须降级。

### 7.4 M2：时间、单位、土层和空间预处理

**输入**：M1 已验收映射及原生文件。

**冻结处理顺序**

```text
原生QC → 单位／符号转换 → 日／候聚合 → 垂直层水量 → 空间重采样／面积聚合
```

不得先重采样再做原生 QC；分类数据不在本模块插值类别编号。

**处理要点**

- 生成73候日历，ERA5-Land 以 UTC 时间戳生成日界和候界。
- 累计量按 M1 判定决定是否差分；已聚合区间总量不得再次差分。
- 水量 m×1000 转 mm；蒸发符号由元数据和水量平衡单元测试共同确认。
- 候通量要求日记录完整；候状态均值至少4有效日且连续缺失不得超过2天。
- ERA5-Land 计算0—100 cm储量，并保留100—289 cm深层；GLDAS 计算0—100 cm并保留100—200 cm深层。
- 连续状态和通量面积加权；总水量先守恒汇总再除以目标格点有效面积。
- 有效原生面积<0.70记缺失；0.50／0.85只作为独立敏感性运行。
- GLDAS 重网格不改变信息量的声明写入元数据，并保留原生0.25°运行接口。

**冻结输出**

```text
data/frozen/{run_id}/time_pentad_calendar.parquet
data/frozen/{run_id}/grid_day_{product_code}.parquet
data/frozen/{run_id}/grid_pentad_base_{product_code}.parquet
data/frozen/{run_id}/grid_static_covariates.parquet
outputs/{run_id}/reports/m2_accumulation_tests.json
outputs/{run_id}/reports/m2_sign_and_balance_tests.json
outputs/{run_id}/reports/m2_area_conservation.csv
outputs/{run_id}/reports/m2_pentad73_audit.csv
```

**必须通过的单元测试**

- 平年／闰年73候日期无重叠、无空洞；
- 第73候5／6天及5天等价量正确；
- 三类累计量样例不会被一律差分；
- 正／负蒸发符号只转换一次；
- ERA5 层厚权重0.07／0.21／0.72及GLDAS层求和正确；
- 重采样前后有效域总水量在数值容差内守恒；
- 低于面积阈值时输出缺失而非低质量数值。

### 7.5 M3：静态掩膜、动态物候与各产品独立气候态

**输入**：M2 物理量、MCD12Q1／Q2 原生数据、网格和研究区。

**处理**

1. 原生解码 MCD12Q1／Q2 QA，先算类别／质量面积，再聚合。
2. 保留 IGBP 1—10、12、14；有效记录≥10年；原生排除类≥0.80永久排除；格点植被面积≥0.50。
3. 逐年地类只作协变量／分层；基线掩膜和无地类掩膜独立敏感性。
4. 物候主保留 Best／Good；多周期取并集；当年面积≥0.50且≥30原生像元才采用当年窗。
5. 当年无效回退格点全部有效年份中位 SOS／EOS；2000年同样回退；有效年份<5主分析缺失。
6. 生成活跃窗长表和 L；物候方案变化时同步改变事件资格、L 和后续植被年合成。
7. 每套产品分别按2000—2023、候±1、n≥40计算 SMP、P95、W；禁止跨产品套阈值。
8. P95含零样本，实际事件另需P>1 mm；P95=0或非零样本<20时R分支不可用。
9. 分别保存各自完整样本与共同支撑样本；共同掩膜不得静默替换主样本。

**冻结输出**

```text
data/frozen/{run_id}/grid_mask.parquet
data/frozen/{run_id}/grid_phenology_year.parquet
data/frozen/{run_id}/grid_phenology_segment.parquet
data/frozen/{run_id}/grid_active_pentad.parquet
data/frozen/{run_id}/grid_climatology_{product_code}.parquet
data/frozen/{run_id}/grid_pentad_{product_combo}.parquet
data/frozen/{run_id}/support_manifest.json
outputs/{run_id}/reports/m3_phenology_fallback.csv
outputs/{run_id}/reports/m3_mask_selection_audit.csv
outputs/{run_id}/reports/m3_climatology_support.csv
```

**验收**

- 每个格点—候可追到气候态样本数、P95、零降水比例和回退状态；
- 固定4—9月、气候态物候、完整案例、Best-only和面积阈值均作为独立方案，不覆盖主动态窗；
- 输出各方案事件纳入率所需的活跃窗版本，并保留纳入／排除事件年份—季节—地类审计接口。

### 7.6 M4：全部骤旱事件库与区域连接

**输入**：M3 `grid_pentad`、活跃窗和支撑表。

**主识别**

1. 从 SMP 连续<40%片段开始，片段前存在最近>40%候，片段最低<20%。
2. t_s 为首次<40%候；最近>40%候至 t_min 平均下降速率≥5百分位／候。
3. 并列最低取首次 t_min；缺测打断连续片段，不跨缺口连接。
4. 主终止为最低点后首次SMP>20%；总持续≥4候；>40%终止和发展期持续定义分别独立建库。
5. 到数据末端未终止者保留为右删失，不进入条件 A，但进入恢复风险和路线二适用队列。
6. 路线一 A 的 t_s、t_e 活跃窗要求与恢复风险的 t_s、t_min 活跃窗要求分别打标，不能用一个过滤条件覆盖全部事件。
7. SESI／SESR 交叉定义只检验旱相定义敏感性，不做多数投票合并；PET 近零时设置分母下限并显式标记，分母下限数值须来自M0配置而非代码硬编码。

**区域连接与质控**

- 同候4邻域连通，相邻候空间重叠或4邻域连接时链接；初始 footprint≥3个0.1°格点。
- 分层随机至少30事件，覆盖产品、前／中／后期、恢复／右删失、窗口不完整和R／Z交集适用情形，人工核对起止、最低点和速率。
- 人工一致率目标100%；不一致是代码错误，禁止调阈值凑一致。

**冻结输出**

```text
data/frozen/{run_id}/event_candidate_audit.parquet
data/frozen/{run_id}/event_master_base.parquet
data/frozen/{run_id}/event_regional.parquet
data/frozen/{run_id}/event_regional_member.parquet
outputs/{run_id}/reports/event_manual_qc.csv
outputs/{run_id}/reports/m4_event_sample_flow.csv
```

### 7.7 M5：恢复、P-term、F_R／F_Z、Lag 与湿过程

**输入**：M4 事件骨架、M3 P／P95／W 与日历。

**恢复与窗口**

- 恢复段固定 `t_min→t_e`，计算 RT、ΔSMP、RR、恢复段Sen斜率、前2候早期速率和t_e后1—5候轨迹。
- P-term 主窗 `[t_min,t_e+2]`；保存全部合格降水候，首个为 t_P95。
- F_R／F_Z 主窗 `[t_e-1,t_e+1]`；±2候为敏感性。
- F_R 首个 t_w 分 pre／sync／post；Q2a 条件比例用全部F_R，H1只用pre＋sync，post不进入非F_R对照。
- F_Z 要求 W1<0、W2≥0.5；阈值0.84／1.28为敏感性。
- 各分支围绕自己的 t_w 计算 W1、W2 和 DFAI。
- P-term需完整至t_e+2，F_R／F_Z需完整至t_e+1；不完整为未知，不归阴性。
- 非P-term的已恢复事件不自动等于“无降水平稳恢复”；仍须另报窗口内降水累积和最大候降水。
- F_R／P-term未知比例按年份、季节和产品报告，并比较未知与已知事件的样本构成。
- 连续合格湿候共享 wet_process_id；允许间隔1个非合格湿候合并仅作敏感性。

**冻结输出**

```text
data/frozen/{run_id}/event_master.parquet
data/frozen/{run_id}/event_precip.parquet
data/frozen/{run_id}/event_branch.parquet
data/frozen/{run_id}/event_recovery_trajectory.parquet
data/frozen/{run_id}/wet_process_membership.parquet
data/frozen/{run_id}/superblock_membership.parquet
outputs/{run_id}/reports/m5_window_completeness.csv
outputs/{run_id}/reports/m5_lag_domain_audit.csv
outputs/{run_id}/reports/m5_branch_overlap.csv
```

**断言**

- `Lag_P` 非空当且仅当 P-term 阳性且有首个合格候；
- `Lag_FR`／`Offset_FR` 非空当且仅当 F_R 阳性且 t_w_R 有效；
- F_R_post 不得进入 H1 的非F_R对照；
- R／Z交集在分支表保留两行，总体FD-WT计数按episode去重；
- 非FD-WT的A没有虚构t_w。

### 7.8 M6：LAI／NDVI 年合成、五年暴露与深层水连接

**输入**：M3物候／掩膜、M4／M5事件、MCD15A3H、MOD13Q1、M2深层与浅层水。

**LAI／NDVI 年合成**

1. 原生 QC 后，LAI 乘0.1，NDVI乘0.0001。
2. LAI 合格4天观测按与候重叠天数加权到候；年生长季值取活跃窗内有效候平均。
3. NDVI 主保留 reliability 0／1并解码VI Quality；采用与LAI相同活跃窗和完整性规则。
4. 年值要求时间覆盖≥0.70、空间有效面积≥0.70；不足则缺失。
5. 严格 Best-only 等QC、覆盖阈值和物候方案均通过新版本独立运行，不覆盖主年值。

**事件暴露**

- 对事件年 y 使用 y−5…y−1 五个完整日历年；主分析5／5有效，4／5为敏感性。
- 计算 `LAI_base` 五年生长季均值和 `LAI_trend` Theil–Sen斜率；保存原单位和1SD标准化版本；分地类报告时另给地类内标准化结果。
- 2008—2023才进入五年LAI模型；早期事件保留在总体库。
- NDVI直接比较只在2008—2023共同事件、同窗口、同掩膜中进行；NDVI是绿度指标稳健性，不是LAI真值验证。
- 深层主暴露为t_s−4…t_s−1平均，再按同产品、同格点、同日历候转百分位／标准化距平。
- 同时保存浅层事件前状态，但不得把浅层、深层和LAI无区别塞入同一模型。
- 五年斜率报告分布、逐年留一范围和异常值影响；很小斜率不直接命名确定绿化／退化。

**冻结输出**

```text
data/frozen/{run_id}/vegetation_grid_year_lai.parquet
data/frozen/{run_id}/vegetation_grid_year_ndvi.parquet
data/frozen/{run_id}/event_exposure.parquet
data/frozen/{run_id}/event_master_v1_3_1.parquet       # 自动连接兼容视图
data/frozen/{run_id}/exposure_cluster_audit.parquet
data/frozen/{run_id}/exposure_cluster_summary.parquet
outputs/{run_id}/reports/m6_lai_trend_diagnostics.csv
outputs/{run_id}/reports/m6_leave_one_year_out.csv
outputs/{run_id}/reports/m6_exposure_missingness.csv
outputs/{run_id}/reports/m6_phenology_selection_audit.csv
```

**验收**

- 所有暴露时间戳严格早于t_s；无后值回填；
- 2008年前事件的LAI缺失原因明确，但不从总体事件库删除；
- 同一grid_id×year的LAI_exposure_cluster一致；
- 报告n_event、n_exposure、簇大小中位数／最大值／P95、单簇贡献和保守EPV／n_eff；
- 固定种子每簇抽1事件和逆簇大小加权仅作敏感性，种子来自M0。

### 7.9 M7：路线一描述、恢复风险、Q1—Q3 与趋势

**输入**：M4—M6冻结表；不读取M8结果。

**先审计、后拟合**

在查看暴露—结局效应前，先生成：

```text
n_event, n_exposure, n_outcome, n_nonoutcome, n_block,
n_superblock, n_eff, EPV, conservative_EPV, missingness,
censoring_pattern, convergence_feasibility
```

随后冻结有效自由度。支撑不足依次：减自由度 → 使用预设核心协变量 → 惩罚模型 → 仅描述；不得按p值删协变量。

**主分析任务**

1. Q1：RT中位数／IQR；ΔSMP、RR均值／中位数及95%区间；区域和地类描述。
2. 恢复风险：全部合格事件离散时间cloglog；t0=t_min、H=12、df=3、可跨季末；行政／缺失删失分列。
3. Q2a：已终止A中的F_R条件比例和Lag_FR；P-term的Lag_P另表。
4. Q2b／H1：F_R_pre／sync与非F_R的RR、ΔSMP中位数回归；post不进对照。
5. F_R：事件级二项logit；格点—年E1b仅汇总对照；E1a负二项+log(L)仅补充。
6. Q3：分别拟合模型L／D／I的恢复风险与F_R；ΔSMP／RR暴露模型为次级。
7. 交互：除link尺度项外，在深层水P25／P50／P75输出LAI边际效应和概率／风险尺度结果。
8. 区间：100km空间块bootstrap500次为主；跨块cluster／wet_process合并超级块；空间×年份双向聚类并列，不一致取较宽区间；50／200km和年份wild cluster bootstrap为敏感性。
9. 趋势：Sen＋MK；至少18有效年；lag-1 Ljung–Box p<0.05时主报告Hamed–Rao，始终修正为敏感性；同时报告L、N_A、物候回退率和数据完整性变化，并比较基线掩膜的年份—地类样本构成。
10. 多重检验：Q1三趋势、Q2两对比、Q3四检验分别家族内Holm α=0.05；地图BH-FDR q=0.05。

**冻结输出**

```text
data/frozen/{run_id}/route1_recovery_person_pentad.parquet
data/frozen/{run_id}/analysis_dataset_{analysis_id}.parquet
outputs/{run_id}/models/model_fit_manifest.parquet
outputs/{run_id}/models/model_result.parquet
outputs/{run_id}/models/model_marginal.parquet
outputs/{run_id}/models/model_object_{analysis_id}.bin
outputs/{run_id}/tables/q1_recovery_distribution.csv
outputs/{run_id}/tables/q1_recovery_risk.csv
outputs/{run_id}/tables/q1_trend_result.csv
outputs/{run_id}/tables/q2_fr_conditional_proportion.csv
outputs/{run_id}/tables/q2_lag_result.csv
outputs/{run_id}/tables/q2_h1_contrast.csv
outputs/{run_id}/tables/q3_model_ldi_effects.csv
outputs/{run_id}/tables/q3_interaction_margins.csv
outputs/{run_id}/tables/multiplicity_result.csv
outputs/{run_id}/tables/sample_support.csv
outputs/{run_id}/tables/censoring_audit.csv
outputs/{run_id}/tables/power_and_mde.csv
outputs/{run_id}/reports/m7_model_diagnostics.jsonl
```

**补充分析接口**

- ΔSMP／RR均值模型为敏感性；0.25／0.75分位仅n≥80且n_eff≥40时估计。
- GAM edf≤3仅辅助形状；PSM仅高／低LAI趋势补充ATT；重叠权重改为ATO时必须明确。
- 等价结果使用预设OR或±0.10 SD界；功效<0.80的非显著只写证据不足。
- 候尺度循环位移零模型1000次，保存C_obs、零分布、RR_coinc和单侧经验p；不单独作物理解释证明。

### 7.10 M8：路线二三出口随访、门槛与退出

**输入**：全部M4事件、M5 F_R和窗口状态、可选M6暴露。

**M8a 随访构造**

- t0=t_s，H=12，全部合格事件进入；6／18为独立敏感性。
- 每候判断首次恢复；A／B首次吸收，C仅在H未恢复时确定。
- B需要t_e+1；H恢复需H+1，否则类型未知而非A。
- 极端降水未恢复保留风险集；季末不删失；删失另编码。
- 严格敏感性仅将F_R_post定义的B改为A_strict；主出口不变。

**M8b 统计与自动门槛**

- A／B原因别离散logistic风险，时间基线受限三次样条df=3；C由H时风险集生存概率得到。
- 主报告原因别风险比、A／B累计发生曲线、C概率和中位离场时间；普通多项logit仅用于固定H且完整随访的对照，不处理右删失，不作主模型。
- 总体描述用2000—2023；加入五年LAI只用2008—2023。
- 多变量探索需n≥200、A／B／C各≥30、100km块≥20、EPV合格。
- 正式区间另需n_eff≥100，且没有单一空间块贡献超过20%的B。
- 可升级为正文核心扩展还需：至少一个预设“LAI／深层水—出口类型或离场时间”对比的95%区间排除无效值，且跨GLDAS／CHIRPS、H=6／18和F_Z重分类方向稳定，规范曲线同方向比例≥0.80。
- B<30、有效块<10、严重分离、跨产品出口结构消失，或只重复F_R比例而无新增时间／路径认识时退出主模型。
- 即使升级正文核心扩展，仍标记为预设探索性。

**冻结输出**

```text
data/frozen/{run_id}/route2_person_pentad.parquet
data/frozen/{run_id}/route2_exit.parquet
outputs/{run_id}/tables/route2_sample_audit.csv
outputs/{run_id}/tables/route2_exit_description.csv
outputs/{run_id}/tables/route2_cif.csv                  # 达相应门槛时
outputs/{run_id}/tables/route2_model_result.csv         # 达相应门槛时
outputs/{run_id}/tables/route2_strict_sensitivity.csv   # 达相应门槛时
outputs/{run_id}/reports/route2_gate.json
outputs/{run_id}/reports/route2_exit_report.md          # 退出时仍必出
```

**失败退路**：不达标只描述或整段退出；退出文件必须列出触发门槛和样本审计，不生成虚假模型结果，不影响M7。

### 7.11 M9：跨产品、站点、规范曲线与可选环流

**输入**：四套产品组合及GLDAS原生运行、规范矩阵、站点和可选环流数据。

**跨产品**

- 四套组合均从自身数据计算SMP、P95、W和深层百分位。
- 格点事件匹配：同一对应格点、|t_min差|≤1候且|t_s差|≤1候；多候选以最小时间差一对一最优匹配。
- 区域事件匹配：时间重叠≥1候且footprint相交；多候选按最大空间IoU一对一。
- ±2候、相邻1格和IoU≥0.10为敏感性。
- 报告双向命中率 matched/N_main、matched/N_alt 与 Jaccard；匹配只用于清单一致性，不替代效应一致。

**站点分轨**

- 土壤水站校验相位、起止和异常；主匹配所在格点，3×3邻域敏感性；报告有符号差、MAE、±1／±2候一致率、距平相关和异常符号一致率。
- 降水站校验P95湿候和日期，不用土壤水站验证降水。
- 至少5站、30匹配事件和50有效站点—候配对才计算汇总误差；不足只列个案。
- 期望预警线为：土壤水中位起止误差≤1候、±1候一致率≥0.60、异常符号一致率≥0.70、距平相关≥0.50；这些是项目期望线而非普适定律。
- 未达期望依次检查时制／层深／空间代表性，再降级为异常与相位结论并降低事件日期表述强度；不得反演调参。
- CHIRPS融合站点只作一致性检查；独立验证须未融合或严格留出站点。

**规范曲线**

按estimand分别冻结矩阵、总数和不适用规则；科学上不合理或冗余组合不进入。定义族包括：

```text
终止20／40
总持续／发展期持续
P95／P99／湿候P95
F_R窗口±1／±2
W=0.5／0.84／1.28
物候动态／固定／气候态
LAI 3／5／10年
深层前1／4／12候
ERA5／GLDAS／CHIRPS
DFAI α=2.0／3.2／4.1
```

输出全部规范、族内结果和定义族等权汇总；不适用组合记`not_applicable`，不当失败，也不临时补组合。设同方向比例为r：

- r≥0.80且无主要定义族反向中位效应：`方向稳健`；
- r≥0.80但区间／显著性敏感：`方向稳定、显著性敏感`；
- 0.50≤r<0.80，或主要定义族中位效应量级比超出[0.5,2]：`定义敏感`；
- r<0.50：`不稳健`。

该分级不替代效应量与区间解释，不能以中位方向代替区间。

**共同产品与均值回归检查**

同一ERA5-Land同时提供事件、深层水和恢复结局时，深层暴露必须止于t_s−1，并用GLDAS复验。恢复速率与F_R共享时间窗，二者差异只作概念诊断；对最低值后的均值回归，以未恢复事件、固定随访和替代终止阈值共同检查，不得称为独立物理验证。

**可选环流**

仅对F_R、F_Z、P\F、F\P做500hPa高度、低层风／比湿和IVT合成；n<20只展示案例，20≤n<30探索，n≥30且空间块≥10才给块区间。

**冻结输出**

```text
outputs/{run_id}/tables/cross_product_event_match.parquet
outputs/{run_id}/tables/cross_product_regional_match.parquet
outputs/{run_id}/tables/cross_product_match_summary.csv
outputs/{run_id}/tables/cross_product_effect_summary.csv
outputs/{run_id}/tables/station_sm_validation.csv
outputs/{run_id}/tables/station_p_validation.csv
outputs/{run_id}/tables/station_case_audit.csv
outputs/{run_id}/tables/spec_manifest.parquet
outputs/{run_id}/tables/spec_result.parquet
outputs/{run_id}/tables/spec_family_summary.csv
outputs/{run_id}/tables/spec_equal_weight_summary.csv
outputs/{run_id}/tables/circulation_composite.csv       # 条件性
outputs/{run_id}/reports/m9_robustness_report.md
```

### 7.12 M10：独立复核、偏离、样本流与最终输出

**输入**：所有冻结数据表、模型结果、日志和图表配置。

**复核任务**

1. R6独立复算分层随机至少30事件和所有主表总数。
2. 核对样本流每一步、右删失、缺失删失、未知窗口、F_R_post、Lag定义域和R／Z去重。
3. 核对n_event／n_exposure／n_eff／块数／EPV、收敛、Holm、边际结果和规范总数。
4. 检查路线二退出或升级是否由门槛自动触发，未把探索性追认成验证性。
5. 检查所有偏离是否登记；看过结局后的改动只能标后验探索。
6. 由冻结结果自动生成最终图表和措辞审计，禁止手工改数。

**冻结输出**

```text
outputs/{run_id}/review/review_event_recalc.csv
outputs/{run_id}/review/review_table_totals.csv
outputs/{run_id}/review/review_schema_validation.json
outputs/{run_id}/review/review_deviation_audit.csv
outputs/{run_id}/review/review_wording_audit.csv
outputs/{run_id}/tables/sample_flow.csv
outputs/{run_id}/tables/missing_exclusion_unknown_summary.csv
outputs/{run_id}/result_manifest.json
outputs/{run_id}/reports/final_reproducibility_report.md
outputs/{run_id}/figures/fig01_sample_flow.*
outputs/{run_id}/figures/fig02_recovery_dynamics.*
outputs/{run_id}/figures/fig03_fr_and_lag.*
outputs/{run_id}/figures/fig04_lai_deep_effects.*
outputs/{run_id}/figures/fig05_cross_product_robustness.*
outputs/{run_id}/figures/fig06_specification_curve.*
outputs/{run_id}/figures/fig07_route2_paths.*            # 条件性
```

任何主表不一致均退回责任模块并生成新run_id；不得在M10直接修补数值。

## 8. 核心公式、估计对象与输出域

### 8.1 公式与单位

```text
ERA5-Land 0—100 cm：
S_0_100 = 1000 × (0.07θ1 + 0.21θ2 + 0.72θ3)

恢复：
RT = t_e - t_min                                      [候]
ΔSMP = SMP(t_e) - SMP(t_min)                         [百分位]
RR = ΔSMP / RT                                       [百分位/候]

时间：
Lag_P = t_P95 - t_min                                [仅P-term阳性]
Lag_FR = t_w,R - t_min                               [仅F_R阳性]
Offset_FR = t_w,R - t_e                              [仅F_R阳性]

强度：
W2 = W(t_w)，W1 = W(t_w-1)
DFAI = (W2-W1) × (|W2|+|W1|) × α^(-|W1|)
```

### 8.2 估计对象与允许样本

| 估计对象 | 样本域 | 模型／报告 | 禁止解释 |
|---|---|---|---|
| RT、ΔSMP、RR条件分布 | 已恢复A | 分布、区间、中位数／均值 | 不代表全部起始事件 |
| 首次恢复风险 | 全部合格且满足恢复风险入组者 | 离散时间cloglog，右删失保留 | 不删除未恢复者 |
| E1a | 格点—年且L>0 | 负二项，offset=log(L) | 不只代表急转机制 |
| E1b | 格点—年且N_A>0 | N_FR/N_A条件比例 | 不是全部骤旱总体风险 |
| F_R条件比例 | 已终止A且F_R窗口已知 | 全部F_R；pre／sync／post分列 | 未知窗口不归阴性 |
| H1恢复对比 | A中pre＋sync与非F_R | RR、ΔSMP中位数回归 | post不进非F_R对照 |
| E2a | FD-WT且W1<0、W2>0 | 严格DFAI | W1≥0不是发生样本删除理由 |
| E2b | 全部FD-WT | ΔSMP、RR | 不限于严格强度域 |
| 路线二 | 全部合格事件 | A／B原因别风险、C状态概率 | 删失不是第四出口 |

### 8.3 验证性检验家族

| 家族 | 检验项 | 原假设 | 校正 |
|---|---|---|---|
| Q1 | 区域年度中位RT、ΔSMP、RR三个双侧趋势 | Sen斜率=0 | 家族内Holm α=0.05 |
| Q2 | F_R_pre／sync与非F_R的RR、ΔSMP两个中位数回归 | 调整后组间系数=0 | 家族内Holm α=0.05 |
| Q3 | LAI_trend对恢复风险／F_R主效应；LAI_trend×深层水对二结局交互 | 对应link尺度系数=0，双侧 | 家族内Holm α=0.05 |

- 不声称控制三个家族合并后的全研究错误率。
- Q1分布和Q2比例／Lag首先是估计对象，不强行添加显著性检验。
- F_Z、DFAI、E1a、次级暴露模型、路线二和地图为探索性；格点地图BH-FDR q=0.05。
- 所有检验均报告原始p、调整p、效应量和区间，不只展示显著项。

### 8.4 候尺度随机重叠零模型

1. 每格点、每日历月内，将完整多年湿过程序列相对骤旱终止序列循环位移1000次，排除0位移；保持月份、数量和持续结构。区域场检验时所有格点使用同一组位移。
2. `C_obs` 为各格点主窗口内合格 `episode×branch` 重合数之和；每episode每分支只计首个t_w。格点检验跨格点不去重，区域检验另按cluster_id去重。
3. 输出 `C_obs`、完整零模型分布、`RR_coinc=C_obs/mean(C_null)` 和单侧经验 `p=(1+#(C_null>=C_obs))/1001`。
4. RR_coinc>1且p<0.05只说明重叠高于该零模型期望，不单独证明物理机制或月尺度漏检；同季节分层区组置换为敏感性。

## 9. Workflow 程序入口与交接实现

### 9.1 统一模块入口

每个模块采用相同调用契约，实际编程语言不限：

```text
run_module(
  module_id,
  config_path = config/params.yaml,
  run_id,
  input_manifest_path,
  output_root,
  resume = true,
  overwrite_frozen = false
)
```

`overwrite_frozen=false` 时，发现同名冻结文件且哈希一致则跳过；哈希不一致则报错而不是覆盖。科学修改必须新建run_id并重跑依赖。

### 9.2 输入输出清单

每次模块运行生成 `module_io_{module}.json`：

```text
module_id, run_id, attempt_id, status,
input_files[{path,sha256,schema_version,row_count}],
output_files[{path,sha256,schema_version,row_count}],
params_hash, code_hash, random_seed_id,
upstream_run_ids, downstream_invalidated,
unit_test_report, sample_flow_report, deviation_ids
```

### 9.3 编排器重跑规则

- M0参数变化：所有科学模块失效。
- M1源文件或变量映射变化：该产品M2及全部下游失效。
- M2时间／单位／层厚／聚合变化：对应M3—M9失效。
- M3掩膜／物候／气候态变化：对应M4—M9失效；植被年合成也须同步重跑。
- M4事件定义变化：M5—M9失效，且不得与旧事件库拼接。
- M5窗口／分支变化：M6兼容视图、M7—M9相关结局失效。
- M6暴露变化：只使依赖该暴露的M7／M8／M9分析失效；非LAI总体事件库不应被重删。
- M7模型变化：M9相应效应与规范汇总、M10失效；不自动改变M8。
- M8退出或模型变化：不影响M7科学结果，只更新M9／M10中路线二汇总。

### 9.4 并行与资源边界

- 可按 `product_combo×year×spatial_tile` 并行M2—M4，但合并后必须校验主键和边界连续性。
- 区域cluster、wet_process、跨候窗口和跨年第73候不得被简单按年份切分后独立完结；分区间需读取必要缓冲候。
- 空间块bootstrap以超级块为抽样单位，不能把同一cluster或wet_process拆到不同重抽样侧。
- 大数据表分区只是存储细节，不改变冻结逻辑表名和schema。

## 10. 必出结果包与条件性结果包

### 10.1 无条件必出

1. **恢复动力学**：RT、ΔSMP、RR条件分布；全部合格事件的恢复风险；区域年度趋势和删失审计。
2. **急转与时间**：F_R条件比例、pre／sync／post、Lag_FR、Lag_P、Offset_FR、P／F质控和未知窗口比例。
3. **暴露模型**：模型L／D／I效应、区间、收敛、n_event、n_exposure、n_eff、空间块、EPV和保守口径。
4. **交互量尺**：link尺度项及深层水P25／P50／P75边际效应、预测概率和概率差／风险差。
5. **植被稳健性**：2008—2023同事件、同窗口、同掩膜的LAI／NDVI共同样本比较。
6. **产品稳健性**：四套产品组合及GLDAS原生0.25°复算。
7. **定义稳健性**：按estimand的规范矩阵、全部结果、族内与定义族等权汇总。
8. **透明度**：样本流、所有缺失、排除、未知结局、偏离、版本、参数和代码哈希。

### 10.2 条件性必出

- F_Z、DFAI补充分析；
- 土壤水站与降水站分轨验证；
- 路线二描述、模型或退出审计；
- 可选环流合成；
- PSM／重叠权重、GAM和扩展调整集等补充分析。

条件不满足时输出 `conditional_skipped` 或 `exited` 及原因，不输出空泛的“结果不显著”。

### 10.3 结果文件命名清单

| 内容 | 冻结文件名 |
|---|---|
| 样本流 | `tables/sample_flow.csv` |
| 恢复条件分布 | `tables/q1_recovery_distribution.csv` |
| 恢复风险 | `tables/q1_recovery_risk.csv` |
| 趋势 | `tables/q1_trend_result.csv` |
| F_R比例 | `tables/q2_fr_conditional_proportion.csv` |
| 三类时间指标 | `tables/q2_lag_result.csv` |
| H1对比 | `tables/q2_h1_contrast.csv` |
| L／D／I效应 | `tables/q3_model_ldi_effects.csv` |
| 交互边际量尺 | `tables/q3_interaction_margins.csv` |
| 多重检验 | `tables/multiplicity_result.csv` |
| 样本支撑 | `tables/sample_support.csv` |
| 跨产品匹配 | `tables/cross_product_match_summary.csv` |
| 跨产品效应 | `tables/cross_product_effect_summary.csv` |
| 规范曲线 | `tables/spec_result.parquet`、`tables/spec_equal_weight_summary.csv` |
| 站点验证 | `tables/station_sm_validation.csv`、`tables/station_p_validation.csv` |
| 路线二门槛 | `reports/route2_gate.json` |
| 路线二退出 | `reports/route2_exit_report.md` |
| 独立复核 | `review/review_table_totals.csv` |
| 最终清单 | `result_manifest.json` |

## 11. 单元测试、集成测试与验收清单

### 11.1 M0／M1

- [ ] 五份文档版本均为v1.3.1，参数哈希唯一。
- [ ] 主分析和所有敏感性均能从配置重建，无隐藏默认值。
- [ ] 研究区、站点和环流的“冻结／暂时锁定”状态没有混写。
- [ ] 原始文件哈希、缺年、重复、坐标、单位和累计类型全部留痕。
- [ ] GLDAS非土壤水原生字段未经官方核验时主链停止。
- [ ] 偏离日志即使为空也存在。

### 11.2 M2

- [ ] 73候日历、平年／闰年和第73候5／6天正确。
- [ ] 小时增量、处理步累计和区间总量测试均通过。
- [ ] 蒸发符号、m→mm、K→℃只转换一次。
- [ ] ERA5层厚、GLDAS层求和和深层范围正确。
- [ ] 候通量完整日规则、候状态4日／最长连续缺2日规则正确。
- [ ] 面积加权和总水量守恒通过；有效面积不足记缺失。
- [ ] GLDAS原生网格与重网格结果分版保存，不宣称重网格增加信息。

### 11.3 M3

- [ ] IGBP保留／排除、有效年、原生排除比例和植被面积阈值正确。
- [ ] 分类变量只计算面积比例，没有插值类别编号。
- [ ] 多周期并集、单周期tie-break、Best／Good、回退和有效年<5规则正确。
- [ ] 固定窗、气候态窗和完整案例为独立版本，且同步传递至事件资格、L和植被年合成。
- [ ] 每产品独立气候态；候±1跨年；n≥40；并列平均秩。
- [ ] P95含零、实际P>1 mm、P95=0／非零样本<20时R分支不可用。
- [ ] 各自完整样本与共同支撑样本分开。

### 11.4 M4／M5

- [ ] >40%参照、连续<40%、最低<20%、下降速率和持续定义正确。
- [ ] 并列最低取首次；缺测断段；不同定义不拼接。
- [ ] 右删失保留，条件A和恢复风险入组条件不混用。
- [ ] 随机≥30事件覆盖规定层，人工轨迹一致率100%。
- [ ] RT、ΔSMP、RR和恢复轨迹公式通过合成事件测试。
- [ ] P-term与F_R／F_Z窗口跨年时仍正确。
- [ ] 窗口不完整为未知，不归0；恢复事实仍保留。
- [ ] F_R_pre／sync／post由首个t_w确定；H1不含post对照。
- [ ] Lag_P、Lag_FR、Offset_FR只在各自阳性样本计算。
- [ ] R／Z交集保留不同t_w；FD-WT总数按episode去重。
- [ ] DFAI围绕各分支t_w；严格E2a不删除发生样本。
- [ ] wet_process和跨块superblock连接确定、可复现。

### 11.5 M6

- [ ] LAI／NDVI比例因子、原生QC和缺测非零断言通过。
- [ ] LAI 4天→候按重叠天数加权；年生长季均值使用对应活跃窗。
- [ ] 年值时间／空间覆盖均达0.70；不足为空并写原因。
- [ ] 五年窗严格y−5…y−1；主分析5／5有效；无事件年、事件后或后值回填。
- [ ] 2008年前事件只缺LAI模型，不从总体库消失。
- [ ] LAI_base、LAI_trend原单位和标准化版本均保存。
- [ ] Sen斜率分布、逐年留一和异常值影响已输出。
- [ ] NDVI共同样本限定2008—2023且同事件、同窗口、同掩膜。
- [ ] 深层窗严格t_s−4…t_s−1；ERA5／GLDAS不直接比绝对mm。
- [ ] n_exposure、簇大小、最大簇贡献、保守EPV／n_eff完整。
- [ ] 每簇抽1事件使用M0固定种子；逆簇大小加权限于敏感性。

### 11.6 M7

- [ ] 路线一恢复风险t0=t_min、H=12、df=3、跨季末。
- [ ] SMP缺口在最后连续有效候删失且不重新入组；双删失分别编码。
- [ ] 已恢复条件指标与全部事件恢复风险分表。
- [ ] F_R logit、E1b、E1a、ΔSMP／RR中位数回归样本域不混淆。
- [ ] Q1／Q2／Q3检验家族和Holm校正数量正确。
- [ ] 模型L／D／I分别拟合；核心协变量和完整案例规则正确。
- [ ] 交互同时输出link尺度和P25／P50／P75实际概率／风险尺度。
- [ ] 主区间使用100km×500次；双向聚类并列；不一致采用较宽区间。
- [ ] 趋势至少18有效年，年事件<10的指标缺失，自相关触发Hamed–Rao。
- [ ] n、结局数、n_exposure、块数、n_eff、EPV和收敛在结果表中完整。
- [ ] 不存在根据p值调整协变量、样本、窗口或自由度的代码路径。

### 11.7 M8

- [ ] t0=t_s而非t_min；全部合格事件进入。
- [ ] A／B为首次吸收出口；C仅在H未恢复；删失另列。
- [ ] B分类读取t_e+1；H恢复读取H+1；未知不归A。
- [ ] 极端降水未恢复仍处风险集并单独标记。
- [ ] 季末不删失；新事件另建episode。
- [ ] post严格敏感性只将B改A_strict，不产生第四出口。
- [ ] 描述／多变量／正式区间／退出由冻结门槛自动判定。
- [ ] 路线二退出后M7仍可从M6独立运行。

### 11.8 M9／M10

- [ ] 四套组合各自计算SMP、P95、W和深层百分位。
- [ ] 格点事件t_min与t_s差均≤1候，一对一匹配，无重复计数。
- [ ] 区域事件时间重叠、footprint和最大IoU一对一规则正确。
- [ ] 双向命中率和Jaccard分母正确。
- [ ] 土壤水站与降水站分轨；最低站数／事件数／配对数未达时只列个案。
- [ ] CHIRPS融合站点未被写成完全独立验证。
- [ ] 规范矩阵按estimand冻结，总数、不适用和定义族等权汇总完整。
- [ ] R6独立复算随机事件和全部主表总数；所有差异有退回记录。
- [ ] 最终图表数值与冻结结果表逐项一致；无手工改数。
- [ ] 所有偏离、后验探索、缺失、排除和未知结局均进入最终报告。

## 12. 角色分工与签字接口

| 角色 | 主责模块 | 必须签字／交接 | 不得独自决定 |
|---|---|---|---|
| R1 课题负责人／预注册管理员 | M0、M10 | 参数、版本、偏离、最终样本流和措辞 | 看结果后改主结局或主暴露 |
| R2 数据工程 | M1—M3、M9 | 原始清单、变量映射、QC、格点—候数据 | 按事件结果调整QC |
| R3 事件与恢复算法 | M4、M5、M8a | 事件主表、分支表、删失和单元测试 | 删除右删失或未恢复急降水事件 |
| R4 遥感／物候／暴露 | M3、M6 | 年合成、暴露表、暴露簇和质量报告 | 用事件后植被补暴露 |
| R5 统计建模 | M7、M8b、M9 | 模型脚本、效应、区间、功效和门槛判定 | 按p值选择变量、窗口或家族 |
| R6 独立复核 | M10 | 独立复算、差异记录、通过／退回 | 与主分析者共用未复核最终表 |
| R7 水文／天气学审阅 | M2、M6、M9 | 层深、符号、收支和环流措辞边界 | 把产品一致写成因果或真值 |

一人可兼多角色，但最终主结果必须由R6独立复算。模块变更先由R1登记，再通知所有下游并确定重跑范围。

## 13. 正式冻结项与暂时锁定项

### 13.1 本工作流必须直接实现的正式冻结项

- 路线一独立、恢复动力学第一核心；路线二可退出。
- 四层研究时期和早期LAI缺失规则。
- 原生QC→单位／符号→日／候→垂直层→空间重采样→掩膜／物候→独立气候态→事件识别。
- 主SMP定义、20%主终止、40%敏感性、总持续≥4候目标总体和发展期持续敏感性。
- RT／ΔSMP／RR、P-term窗口、F_R主／F_Z补、三亚型和三个时间指标。
- 五年LAI主暴露、NDVI共同样本、深层水前4候、模型L／D／I。
- 路线一恢复风险t0=t_min／H=12／df=3／跨季末／双删失。
- 路线二t0=t_s／H=12／A／B／C／首次离场／删失规则。
- 核心协变量、Holm家族、BH地图、空间块、年份依赖、EPV和暴露簇审计。
- 四套产品组合、GLDAS原生复算、事件匹配、站点分轨和按estimand规范曲线。
- 删除W2D主线、Noah-MP离线实验、CMIP6必需链和“后果”结局。

### 13.2 只能以状态门实现的暂时锁定项

| 项目 | 当前状态 | 放行条件 | 未放行处置 |
|---|---|---|---|
| 研究区矢量 | 暂时锁定来源、版本、校验值 | M0登记并冻结 | 不生成正式区域结果；变化只触发空间重跑 |
| 站点清单与使用权 | 暂时锁定 | M1完成站点、层深、时制和权限审计 | 主链继续；不声称独立站点验证 |
| 路线二统计升级 | 主参数冻结，升级结果依赖 | 满足样本、区间和稳健性门槛 | 描述或退出，不影响路线一 |
| 第三出口名称 | 冻结“持续未恢复” | 另立并验证常规干旱判据 | 不得改称常规干旱 |
| 可选环流字段 | 变量族冻结，具体字段暂时锁定 | 下载后登记版本、变量和IVT计算链 | 删除该诊断，不影响主链 |
| 随机种子具体值 | v1.3.1未给固定数值 | M0看结局前固定并写入params | 未固定时不得运行涉随机主分析 |
| SESI／SESR的PET近零分母下限 | v1.3.1只冻结“设下限并标记”，未给数值 | 启用该敏感性前由M0登记具体值 | 未登记时不得运行该敏感性，不影响主SMP链 |

## 14. 最小完成标准与最终交付判定

### 14.1 路线一最小完成标准

必须同时具备：

1. 完整原始清单、变量映射、QC和73候时间轴；
2. 全部合格事件库及右删失，而非只有已恢复事件；
3. RT／ΔSMP／RR、恢复风险、F_R／Lag及窗口未知审计；
4. 五年LAI／深层水预设模型和暴露簇样本支撑；
5. 四套产品、GLDAS原生复算、规范曲线和不确定性；
6. 完整样本流、偏离日志和R6独立复核。

路线二、站点和环流不是路线一最小完成标准；其缺失只影响相应扩展和验证措辞。

### 14.2 AI 完成搭建后的交付检查

AI 不应只交付脚本，而应同时交付：

```text
可运行DAG与M0—M10模块入口
params.yaml与schema_registry.yaml
四套产品和敏感性配置生成器
所有核心表的空schema／合成数据测试
模块级与端到端单元测试
输入输出哈希、断点续跑和依赖失效机制
样本流、偏离、模块状态和退出台账
按第10节自动生成结果包的报告入口
```

在合成数据测试未通过前，不得接触正式暴露—结局效应；在数据可行性阶段只能查看完整性、事件数、结局数、暴露支撑、块数和收敛，不得据此挑选科学定义。

## 15. 原文档回查索引

- **详细技术手册**：第2—5节查时期、数据、预处理、掩膜和气候态；第6—9节查事件、恢复、急转、路线二和暴露；第10—13节查模型、验证、表格和参数；第14—15节查角色与冻结状态。
- **预注册文档**：第2节查验证性问题；第5—7节查操作定义、排除和主模型；第8—10节查路线二、稳健性、盲态和偏离。
- **模块化思路理解**：第3—5节查模块接口、责任和交接契约。
- **权威文献引用解释**：查方法借用、尺度匹配和不得越界的解释；本工程文件不得把文献方法迁移写成普适阈值。
- **说明书**：查研究主线、四条时期和最终科学措辞。

> **给实际搭建 AI 的固定附加指令**：严格按本规格实现；所有科学阈值只从第5节对应的 `params.yaml` 读取；模块接口、主键、字段和冻结文件名以第6—7节为准；遇到v1.3.1未明确的原生字段或外部元数据，写入M1待核验状态并停止相关主链，不得自行补造变量名、阈值、样本或因果解释。
