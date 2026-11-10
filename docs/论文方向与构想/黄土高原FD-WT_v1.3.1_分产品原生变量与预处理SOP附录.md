# 黄土高原 FD-WT v1.3.1 分产品原生变量与预处理 SOP 附录

**附录代码**：FDWT-SOP-1.0  
**编制日期**：2026-11-02  
**适用协议**：黄土高原 FD-WT v1.3.1  
**文档性质**：独立工程附录；不替代、不覆盖五份 v1.3.1 科学协议及既有 AI 工作包。

## 0. 使用边界与冻结声明

### 0.1 本附录解决什么问题

本附录把“原生文件”到“项目规范变量”之间的处理固定到可编码、可测试的层级，包括：

1. 官方下载入口、原生字段、短名、单位、比例因子和缺测处理；
2. 有原生 QC 位段的产品给出位段、位值、解码公式和主／敏感性掩膜；
3. 小时、3 小时、日、4 天、16 天、年产品到日／候／年值的聚合公式；
4. 原生网格到 0.1°主网格的面积加权、面积覆盖率和类别比例公式；
5. 平年、闰年、第 73 候、跨年、累计量、蒸发符号、层厚、面积守恒和 QC 解码测试；
6. 官方文档核验与实文件验收分开登记；
7. 每类产品与本课题的匹配度、可迁移部分和不可迁移边界。

### 0.2 不改变的科学内容

本附录不改变以下已冻结口径：SMP 40／20 百分位阈值、5 百分位／候、总持续≥4 候、恢复定义、P-term／F_R／F_Z 窗口、四层研究时段、LAI 事件前五年暴露、动态物候、覆盖阈值、四套产品组合、GLDAS 原生 0.25°复算及统计模型。

本附录新增的仅是工程实现细节。若执行本附录导致事件样本、暴露样本或结局定义发生变化，必须作为新 `run_id` 和偏离事项审计，不得覆盖原结果。

### 0.3 证据等级

| 标记 | 含义 | 能否据此宣称实文件已验收 |
|---|---|---|
| D | 官方产品页、官方用户指南或官方参数文档已核验 | 否 |
| F | 官方或官方镜像的实际数据文件已下载并检查变量、坐标、单位和值域 | 是，但仅限所验文件与字段 |
| P | 规则已给出，但原始文件尚未取得；生产前必须完成 M1 验收 | 否 |

**实文件未验收不等于产品不能用，也不等于字段未知；它意味着本地代码尚需用真实文件证明读取、时间坐标、缺测和 QC 行为。**

### 0.4 本次证据状态总表

| 产品 | 官方文档 | 实文件状态 | 生产门槛 |
|---|---|---|---|
| ERA5-Land | D：CDS 与 ECMWF 数据文档已核验 | P：CDS 权限文件未取得 | 用至少连续 3 天、含 00 UTC 的实文件通过累计量与符号测试 |
| GLDAS-2.1 Noah 0.25° | D：官方 README 与产品目录已核验 | P：Earthdata 原始文件未取得 | 用至少连续 3 天实文件核验 `_FillValue`、时间戳和后缀语义 |
| CHIRPS v2.0 | D：UCSB 产品页已核验 | F：NOAA ERDDAP 官方镜像 NetCDF 子集已验收 | 正式批量仍以 UCSB 原生文件或经登记的官方镜像为准 |
| MCD15A3H.061 | D：LP DAAC 产品页与 V6.1 指南已核验 | P：HDF4 实文件未取得 | 用实 HDF4 验证 SDS 名、整型、QC 解码和 4 天日期 |
| MOD13Q1.061 | D：LP DAAC 产品页与 V6.1 指南已核验 | P：HDF4 实文件未取得 | 用实 HDF4 验证 16 天名义区间、合成日和 QC |
| MCD12Q2.061 | D：LP DAAC 产品页与 V6.1 指南已核验 | P：HDF4 实文件未取得 | 验证 cycle 维、跨年和官方 QA 示例 |
| MCD12Q1.061 | D：LP DAAC 产品页与 V6.1 指南已核验 | P：HDF4 实文件未取得 | 验证 `LC_Type1`、`QC`、`LW` 和年度覆盖 |
| SoilGrids250m | D：ISRIC 文档已核验 | F：官方 WCS GeoTIFF 与原生 VRT 已验收 | 批量冻结所有层的 URL、下载日期、版本和哈希 |
| NASADEM_HGT.001 | D：LP DAAC 产品页与 V1.3 指南已核验 | P：HGT 瓦片实文件未取得 | 验证大端序、3601×3601、瓦片坐标、NUM 和垂直基准 |

## 1. 全局数据契约

### 1.1 原始文件只读与清单

每个下载文件必须写入 `source_file_manifest`，至少包含：

```text
source_id, product_code, collection, official_url, request_url,
download_time_utc, access_route, license, file_name, file_bytes,
sha256, spatial_extent, temporal_extent, crs, variable_names,
unit_metadata, fill_metadata, qc_metadata, evidence_level,
acceptance_status, acceptance_report, supersedes, notes
```

规则：

- 原始文件只读保存，单位转换、QC、裁剪和重投影均写出新文件；
- 清单缺失、哈希改变、产品 collection 改变或时间范围不连续时停止生产；
- 不使用“最新版”作为唯一版本标识；必须记录实际版本、请求和下载日期；
- 不从文件名猜单位，不把常见的 `-9999` 自动套用到所有产品；
- 缺测在规范表中使用空值／NaN 加 `missing_reason`，不得把缺测改成 0。

### 1.2 处理顺序

```text
文件与元数据验收
→ 原生 QC／缺测识别
→ 比例因子、单位和符号转换
→ 原生分辨率时间聚合
→ 垂直层合成（仅土壤水）
→ 面积聚合／保守重网格
→ 年生长季合成与五年暴露（仅植被）
```

禁止：先双线性插值再解码 QC；先重投影类别编号再取整；把填充值乘比例因子后当作物理值；用事件后数据填补事件前暴露。

### 1.3 统一位解码

对无符号整数 `q`，从 `lo` 到 `hi` 的位段定义为：

```text
bits(q, lo, hi) = (q >> lo) & ((1 << (hi-lo+1)) - 1)
```

位号按官方指南的最低有效位为 bit 0。读取有符号整型存储的位字段时，先按位宽转换为对应无符号表示；但 `MCD12Q2 QA_Detailed` 的有效范围仅 0—16383，无需符号扩展。

## 2. 统一时间聚合 SOP

### 2.1 73 候日历

公历年 `y` 的第 `p` 候：

- `p=1,…,72`：第 `5(p-1)+1` 至 `5p` 个日历日；
- `p=73`：第 361 日至年末，平年 5 天、闰年 6 天；
- 日期区间为左闭右闭 `[start_date,end_date]`；
- `t_abs=(year-2000)*73+pentad`，`pentad∈[1,73]`。

输出字段：

```text
t_abs, year, pentad, start_date, end_date, n_days,
is_leap_year, is_pentad73, previous_t_abs, next_t_abs
```

跨季、跨年恢复窗沿 `t_abs` 连接，不能每到 12 月 31 日重置。

### 2.2 状态量与通量量分开

状态量 `x`（土壤水、温度等）：

$$
\bar x_d=\frac{1}{n_d}\sum_{h\in d}x_{dh},\qquad
\bar x_p=\frac{\sum_{d\in p}v_d\bar x_d}{\sum_{d\in p}v_d}.
$$

其中 `v_d` 表示日值有效。候状态值要求至少 4 个有效日，且不得连续缺失超过 2 天；不足则为空。

区间水量 `z`（P、ET、R）先形成日总量 `z_d`，再求候总量：

\[
z_p=\sum_{d\in p}z_d.
\]

候通量要求该候全部日记录有效；任一有效日缺失则候总量为空。第 73 候保留实际 5／6 天总量；仅敏感性另算：

\[
z_{p,rate}=z_p/n_p,\qquad z_{p,5eq}=z_p\times5/n_p.
\]

### 2.3 时间完整性不得变成静默插值

- 不用前后日平均补齐缺测日后再宣称“完整日记录”；
- 不因某候缺失把前后事件片段跨缺口连接；
- 不把未观测窗口归为非 P-term／非 F_R；
- 第 73 候不得丢弃闰年第 366 天；
- 年／候聚合保存 `n_valid`、`n_expected`、`coverage` 和 `missing_reason`。

## 3. 统一空间聚合 SOP

### 3.1 面积权重

设原生像元 `i` 与目标格点 `g` 的交叠面积为 `A_ig`，目标格点研究区内面积为 `A_g`，原生有效指示为 `q_i∈{0,1}`。面积在合适的等面积投影或球面几何上计算，不能直接用经纬度网格的像元个数代替真实面积。

连续强度量或单位面积水量：

\[
x_g=\frac{\sum_i q_iA_{ig}x_i}{\sum_i q_iA_{ig}},\qquad
C_g=\frac{\sum_i q_iA_{ig}}{A_g}.
\]

当 `C_g<0.70` 时，`x_g` 为空；0.50／0.85 为独立敏感性。所有权重和覆盖率必须保存，不能只保留聚合值。

对单位面积水量 `mm`，该公式就是面积加权平均；若检查区域总水量，则使用：

\[
V_g=x_gA_g^{valid},\qquad A_g^{valid}=\sum_i q_iA_{ig}.
\]

### 3.2 类别变量

类别 `k` 的面积比例：

\[
f_{gk}=\frac{\sum_i q_iA_{ig}\mathbf{1}(c_i=k)}{\sum_i q_iA_{ig}}.
\]

不得计算类别编号的算术均值，也不得对 `LC_Type1` 做双线性插值。主地类由冻结的类别映射和面积比例规则确定，并保存全部 `f_gk`，以便审计混合像元。

### 3.3 网格对齐与 GLDAS 特殊规则

- ERA5-Land CDS 0.1°输出与主网格坐标完全一致时只做网格对齐，不再插值；
- CHIRPS、MODIS、SoilGrids、NASADEM 在原生 QC 后面积聚合至 0.1°；
- GLDAS 原生 0.25°复算不进行 0.1°重网格；另一次 0.1°运行使用面积保守重网格，最近邻状态量只作敏感性；
- GLDAS 重网格后的更多行数不是新增独立信息，样本支撑仍须报告原生格点、空间块和超级块。

## 4. ERA5-Land 预处理 SOP

### 4.1 官方来源、版本与下载字段

官方入口：Copernicus CDS `reanalysis-era5-land`；使用小时产品，不使用月产品反推候值。  
数据集 DOI：https://doi.org/10.24381/cds.e2161bac  
数据论文 DOI：https://doi.org/10.5194/essd-13-4349-2021

| CDS 变量名 | GRIB 短名 | 原生单位 | 时间类型 | 项目字段 | 用途 |
|---|---|---|---|---|---|
| `volumetric_soil_water_layer_1` | `swvl1` | m³/m³ | 瞬时 | `sm_l1_m3m3` | 0—7 cm |
| `volumetric_soil_water_layer_2` | `swvl2` | m³/m³ | 瞬时 | `sm_l2_m3m3` | 7—28 cm |
| `volumetric_soil_water_layer_3` | `swvl3` | m³/m³ | 瞬时 | `sm_l3_m3m3` | 28—100 cm |
| `volumetric_soil_water_layer_4` | `swvl4` | m³/m³ | 瞬时 | `sm_l4_m3m3` | 100—289 cm |
| `total_precipitation` | `tp` | m | 从预报起点累计 | `p_raw_m`→`p_mm` | P、P95、P-term、F_R |
| `total_evaporation` | `e` | m of water equivalent | 从预报起点累计 | `et_raw_m`→`et_loss_mm` | 实际蒸散，B |
| `potential_evaporation` | `pev` | m | 从预报起点累计 | `pet_raw_m`→`pet_loss_mm` | SESI／SESR 敏感性 |
| `surface_runoff` | `sro` | m | 从预报起点累计 | `runoff_surface_raw_m` | R 地表部分 |
| `sub_surface_runoff` | `ssro` | m | 从预报起点累计 | `runoff_subsurface_raw_m` | R 地下部分 |
| `2m_temperature` | `t2m` | K | 瞬时 | `t2m_k`→`t2m_c` | 4—9 月热背景 |

**字段校正**：官方 ECMWF 表的 CDS 名是 `sub_surface_runoff`。既有工程规格中的 `subsurface_runoff` 只能保留为历史别名，实际下载映射以官方字段和 CDS 实文件为准。

ERA5-Land 的 CDS 数据是约 9 km 原生模拟插值到规则 0.1°经纬网的结果；不得把 0.1°下载网格写成 0.1°原生动力网格。

### 4.2 缺测与 QC

ERA5-Land 没有 MODIS 式逐像元 QC 位段。处理规则：

1. NetCDF 使用变量实际 `_FillValue`／`missing_value` 和缩放属性；GRIB 使用缺测位图和 GRIB 元数据；
2. 不预设全产品统一缺测码，不把海洋缺测当 0；
3. 土壤水检查物理范围 `0≤θ≤1`，降水／径流检查非负，温度做合理范围审计；
4. 使用最终 consolidated 数据，不与 ERA5-Land-T 混拼；2000—2023 主期不受近期 NRT 更新影响，但仍保存 `expver`／来源信息；
5. 不用 ERA5-Land 的 LAI 字段替代 MCD15A3H：官方文档说明其 LAI 基于月气候态，不能提供本项目所需年际变化。

### 4.3 累计量的唯一正确处理

ERA5-Land 小时累计量从每日 00 UTC 预报起点累计至 forecast step。CDS 使用有效时间：

- `D 01:00` 至 `D 23:00` 对应 `D 00` 起报的 step 1—23；
- `D+1 00:00` 对应 `D 00` 起报的 step 24；
- `D 00:00` 是前一日的 step 24，属于前一日累计区间。

令 `C(t)` 为以 m 表示的累计值。UTC 日 `D=[D00,D+1 00)` 的日总量直接为：

\[
Z_D=1000\,C(D+1\ 00{:}00)\quad [mm].
\]

若确需小时增量：

\[
a_{D,h}=C(D,h)-C(D,h-1),\ h=1,\ldots,23,
\]
\[
a_{D,24}=C(D+1,00)-C(D,23).
\]

然后 `Z_D=1000Σ_h a_D,h`。两种方法应数值等价；**不得把 24 个累计值直接相加，也不得把 `D00` 再加入日 D。**

下载时必须比研究末日多取一个 `00 UTC` 有效时次。若使用 CDS 已生成日统计产品，则按其实际区间元数据处理，不再差分；主链优先从小时累计量自行复算。

### 4.4 蒸发、PET 与径流符号

ECMWF 的蒸发变量通常以负值表示向上蒸发、正值表示凝结。经实文件确认该符号后：

\[
ET_{loss}=-1000\,E_{raw},\qquad PET_{loss}=-1000\,PEV_{raw}.
\]

若实文件或另一导出链已经给正值损失量，则不得再次取负。实际 ET 出现净凝结时可保留负的 `ET_loss` 并标记，不为追求非负而截断水量平衡。PET 的近零分母下限只用于 SESI／SESR，不改变原始 PET 或主链 B。

\[
R=1000(SRO+SSRO),\qquad B=P-ET_{loss}-R.
\]

ERA5-Land 的 `total_evaporation` 是实际蒸散；ERA5-Land PEV 是开放水面蒸发定义，不能写成农业参考作物蒸散。

### 4.5 土壤水垂直层合成

小时值先按同一时次合成储量，再做日／候平均：

\[
S_{0-100}=1000(0.07\theta_1+0.21\theta_2+0.72\theta_3),
\]

\[
S_{deep}=1000\times1.89\theta_4.
\]

单位均为 mm。四层范围为 0—7、7—28、28—100、100—289 cm。深层暴露仍按协议取事件前 4 候均值后转同产品、同格点、同日历候百分位／标准化距平。

### 4.6 日／候聚合与空间处理

- `swvl1—4`：24 个瞬时小时值求日均，再按状态规则求候均；
- `t2m`：24 小时均值，日均后再减 273.15 得 °C；4—9 月均温由完整日值聚合；
- P、ET、PET、SRO、SSRO：先形成 UTC 日总量，再对完整日求候总量；
- 已在 0.1°主网格上的 ERA5-Land 不再做空间重采样；仅按研究区掩膜保留格点并保存土地覆盖有效性。

### 4.7 必过数值测试

**测试 E1：累计量日界。** 设：

```text
C(D,00)=0.0080       # 前一日总量，不属于日D
C(D,01)=0.0002
C(D,02)=0.0005
C(D,23)=0.0040
C(D+1,00)=0.0050
```

则日 D 总量为 5.0 mm；小时 1、2、24 增量分别为 0.2、0.3、1.0 mm。若结果包含前一日 8.0 mm 或把所有 C 相加，测试失败。

**测试 E2：蒸发符号。** 日累计 `e=-0.003 m` 时，`et_loss_mm=3.0`；若输入已是 `+3 mm loss`，则保持 3.0，不得变成 −3.0。

**测试 E3：层厚。** `θ1=0.10、θ2=0.20、θ3=0.30、θ4=0.40`，则 `S0-100=265 mm`，`Sdeep=756 mm`。

**测试 E4：第 73 候。** 2020-12-26—2020-12-31 共 6 天，日 P 均为 1 mm，则候总量 6 mm、日速率 1 mm/day、5 天等价量 5 mm。

### 4.8 与课题匹配度

**匹配度高**：小时累计量、四层土壤水和 0.1°规则网格可支撑候尺度 SMP、深层水、P／ET／R 和恢复窗。  
**边界**：再分析不是站点真值；CDS 0.1°不是新增原生信息；降水与土壤水同模型链，跨 CHIRPS／GLDAS 仍需复算；PEV 定义不得误写。

## 5. GLDAS-2.1 Noah 0.25°预处理 SOP

### 5.1 官方来源与下载字段

官方产品：`GLDAS_NOAH025_3H.2.1`，3 小时、0.25°、NetCDF-4。  
数据集 DOI：https://doi.org/10.5067/E7TYRXPJKWOQ  
GLDAS 方法论文 DOI：https://doi.org/10.1175/BAMS-85-3-381

只使用主生产流，不与 `_EP` Early Product 混用。

| 原生字段 | 原生单位 | 后缀语义 | 项目字段 | 转换 |
|---|---|---|---|---|
| `SoilMoi0_10cm_inst` | kg/m² | 瞬时 | `sm_0_10_mm` | 水量上 1 kg/m²=1 mm |
| `SoilMoi10_40cm_inst` | kg/m² | 瞬时 | `sm_10_40_mm` | 同上 |
| `SoilMoi40_100cm_inst` | kg/m² | 瞬时 | `sm_40_100_mm` | 同上 |
| `SoilMoi100_200cm_inst` | kg/m² | 瞬时 | `sm_deep_mm` | 同上 |
| `Rainf_f_tavg` | kg/m²/s | 过去 3 小时平均强迫降水率 | `p_rate_kgm2s` | 乘 10800 得该 3 小时 mm |
| `Evap_tavg` | kg/m²/s | 过去 3 小时平均实际蒸散率 | `et_rate_kgm2s` | 乘 10800 得该 3 小时 mm |
| `Qs_acc` | kg/m² | 过去 3 小时累计地表径流 | `runoff_surface_mm` | 直接按 mm 累计 |
| `Qsb_acc` | kg/m² | 过去 3 小时累计地下径流／基流 | `runoff_subsurface_mm` | 直接按 mm 累计 |

`Qsm_acc` 是雪融水，不等于径流，不加入 R。`PotEvap_tavg` 原生单位为 W/m²，不是 mm；主链不下载它冒充 PET 水量。若未来另做 PET 敏感性，必须单独做能量—水量转换和预注册。

### 5.2 缺测与 QC

- GLDAS 无逐像元位掩码 QC；
- 官方 README 未给所有文件一个可无条件写死的统一缺测码；M1 必须读取每个变量的 `_FillValue`／`missing_value`；历史文件中常见的 `-9999` 只能作为待核验候选，不得代替元数据；
- 2020 年 10 月官方对内陆水体的模型输出做过掩膜后处理，2020-11-01 前下载的旧文件不应与后处理文件混用；正式项目统一下载当前主生产流并记录哈希；
- 气象强迫字段和模型状态／通量字段的内陆水掩膜行为可能不同，不能用某一字段有值推断全部字段有效；
- 土壤水四层均须非负，降水、ET、径流做非负与极端值审计；异常只标记，未经物理依据不自行截断。

### 5.3 时间轴与日／候聚合

官方后缀定义：`_inst` 为瞬时，`_tavg` 为向后 3 小时平均，`_acc` 为向后 3 小时累计。日 D 的区间是 `[D00,D+1 00)`：

- 瞬时土壤水使用 D00、03、06、09、12、15、18、21 共 8 个时次求日均；
- 向后平均／累计量按其所代表区间归入日 D，即有效时间 D03、06、09、12、15、18、21 和 D+1 00；实文件若时间坐标语义不同，必须先修正映射并通过跨日测试，不能机械按文件日期分组。

对每个 3 小时块 `b`：

\[
P_b=10800\,Rainf\_f\_tavg_b,\qquad ET_b=10800\,Evap\_tavg_b,
\]
\[
R_b=Qs\_acc_b+Qsb\_acc_b.
\]

日通量 `P_D、ET_D、R_D` 为 8 块之和，缺一块则日通量缺失。日土壤水先计算：

\[
S_{0-100,b}=SM_{0-10,b}+SM_{10-40,b}+SM_{40-100,b},
\]

再对 8 个时次求日均；深层 `Sdeep=SM100-200`。日值进入统一候规则：状态至少 4 有效日且连续缺失不超过 2 天，通量要求完整日。

### 5.4 空间处理

原生 0.25°全链复算是必要结果，不只保留重网格结果。另做 0.1°敏感性时，对日／候单位面积水量和状态量使用第 3 节面积保守公式。不能把 0.25°像元复制到多个 0.1°格点后当作新观测。

ERA5-Land 与 GLDAS 深层厚度不同：100—289 cm 对 100—200 cm。只比较各自产品内部的标准化状态和效应方向，不直接比较深层 mm 谁更大。

### 5.5 必过数值测试

**测试 G1：速率转水量。** 若 8 个 3 小时块 `Rainf_f_tavg=0.0001 kg/m²/s`，则日 P 为：

```text
8 × 0.0001 × 10800 = 8.64 mm
```

若再乘 24 小时或把 `_tavg` 当 `_acc`，测试失败。

**测试 G2：累计量不重复乘秒。** 若 8 块 `Qs_acc=0.1`、`Qsb_acc=0.05 mm`，则日 R=1.2 mm，不得再乘 10800。

**测试 G3：土壤水层求和。** 若三层日值分别为 10、30、60 mm，则 `S0-100=100 mm`；若深层为 150 mm，则 `Sdeep=150 mm`，不能把四层都纳入 0—100 cm。

**测试 G4：水量平衡。** 若日 P=8.64、ET=1.728、Qs 合计=0.8、Qsb 合计=0.4 mm，则 B=5.712 mm。

### 5.6 与课题匹配度

**匹配度高**：提供另一条陆面模型链和 100—200 cm 深层水，适合检验恢复及深层水关联是否依赖 ERA5-Land。  
**边界**：不是完全独立观测验证；0.25°信息较粗；主生产流与 EP、旧版内陆水体文件和不同深层厚度均须分开。

## 6. CHIRPS v2.0 预处理 SOP

### 6.1 官方来源、字段与实文件证据

官方产品：UCSB Climate Hazards Center CHIRPS v2.0，日尺度、0.05°、50°S—50°N。  
数据论文 DOI：https://doi.org/10.1038/sdata.2015.66

本次从 NOAA ERDDAP 的 CHIRPS v2.0 官方镜像取得实际 NetCDF 子集；镜像元数据 `history` 明确记录其从 UCSB 官方目录同步。样例范围：2020-06-01—2020-06-02、107.0—107.1°E、37.0—37.1°N。

实文件验收结果：

| 项目 | 实测结果 |
|---|---|
| 变量 | `precip`，`float32` |
| 单位 | `mm/day` |
| `_FillValue`／`missing_value` | −9999.0 |
| 时间 | `seconds since 1970-01-01T00:00:00Z`；注释为日开始时间 |
| 数组形状 | time=2、latitude=3、longitude=2 |
| 纬度／经度 | 0.05°网格中心 |
| SHA256 | `287c36f28375d8ef37c3dd37ccf08974cdddb131c995f106c5660fdda1e5b521` |

既有工程规格中的 `precipitation` 是语义名；实际 NetCDF 映射以 `precip` 为主，并允许 M1 将其他官方格式中的等价字段映射到 `p_mm_day`。

### 6.2 缺测、QC 与数值保留

- CHIRPS 没有 MODIS 式逐像元 QC 位段；不得伪造 QC bit；
- 原生缺测码以实文件元数据为准，本次 NetCDF 为 −9999；
- 降水物理上不应为负；除缺测码外的负值进入异常审计，不直接当 0；
- 很小的正值和 0 均保留，不把浮点近零值人为改成 0，也不因 0 降水多而删除样本；
- 融合站点意味着它是不同降水源的一致性检查，不是完全独立验证。

### 6.3 日／候聚合

日文件中的 `mm/day` 对长度为 1 天的区间数值上等于日 mm：

\[
P_d=precip_d\times1\ day.
\]

候总量为完整日之和：

\[
P_p=\sum_{d\in p}P_d.
\]

要求该候 5／6 天全部有效。第 73 候保留真实总量，并按统一规则另算日速率／5 天等价敏感性。P95 必须由 CHIRPS 自身 2000—2023 候序列、同日历候±1 池重新计算，不得套用 ERA5-Land 或 GLDAS 阈值。

### 6.4 空间聚合

在原生 0.05°日降水完成缺测识别后，对每个日场按第 3 节面积加权至 0.1°，再进入候聚合。也可先候聚合再面积聚合，但同一主运行必须固定一种顺序；本附录固定为：

```text
原生日缺测识别 → 日面积聚合 → 完整日检查 → 候求和
```

日面积覆盖率低于 0.70 时该日格点缺失。不得用双线性插值制造虚假降水中心。

### 6.5 必过数值测试

**测试 C1：单位。** `precip=7.581008 mm/day` 对应日水量 7.581008 mm，不再除 24 或乘 86400。

**测试 C2：候总量。** 平年第 73 候日值为 `[0,1,2,0,3] mm`，结果 6 mm；闰年增加第 6 天 1 mm，结果 7 mm。

**测试 C3：缺测。** 任一日为 −9999 时，候 P 为空并标 `missing_daily_input`，不能按其余 4 天求和后当作完整候。

**测试 C4：近零值。** 实文件中约 `1.1×10⁻⁵ mm/day` 的值保留，不归零。

### 6.6 与课题匹配度

**匹配度中高**：0.05°日降水适合作为 P95、P-term、F_R 和 W 的替换降水源。  
**边界**：只替换降水，不提供土壤水；融合站点不独立；当前出现的 CHIRPS v3 具有不同的日尺度分配方法，不得静默替代已冻结的 v2.0，若未来换版必须另立版本和完整重跑。

## 7. MCD15A3H.061 预处理 SOP

### 7.1 官方来源与下载字段

产品：4 天、500 m、MODIS Sinusoidal，2002-07-04 起。  
数据集 DOI：https://doi.org/10.5067/MODIS/MCD15A3H.061  
算法背景论文 DOI：https://doi.org/10.1016/S0034-4257(02)00074-3

| 原生 SDS | 类型 | 有效范围 | 填充／特殊值 | 比例因子 | 项目字段 |
|---|---|---:|---|---:|---|
| `Lai_500m` | uint8 | 0—100 | 249—255 为非反演／填充类别 | 0.1 | `lai_native`→`lai` |
| `FparLai_QC` | uint8 | 位字段 | 255 | 无 | `lai_qc_main` |
| `FparExtra_QC` | uint8 | 位字段 | 255 | 无 | `lai_qc_extra` |
| `LaiStdDev_500m`（可选审计） | uint8 | 0—100 | 248—255 按指南审计 | 0.1 | `lai_stddev` |

`Lai_500m=249` 不能乘 0.1 后当 24.9。指南中的 249—255 还区分未分类、城市、湿地、雪冰、裸地、水体和通用填充，全部不进入 LAI 数值平均。

### 7.2 `FparLai_QC` 位段

| 位段 | 名称 | 官方含义 |
|---|---|---|
| bit 0 | `MODLAND_QC` | 0：主算法质量好；1：其他质量、备份算法或填充 |
| bit 1 | `Sensor` | 0：Terra；1：Aqua |
| bit 2 | `DeadDetector` | 0：正常；1：死探测器导致超过 50%相邻探测器反演 |
| bits 3—4 | `CloudState` | 0：无显著云；1：有云；2：混合云；3：未定义并假定晴 |
| bits 5—7 | `SCF_QC` | 0：主 RT 无饱和；1：主 RT 饱和但仍可用；2：几何问题转经验算法；3：其他问题转经验算法；4：未生产 |

### 7.3 `FparExtra_QC` 位段

| 位段 | 名称 | 0／1 或类别含义 |
|---|---|---|
| bits 0—1 | `LandSea` | 0 陆地、1 岸线、2 淡水、3 海洋 |
| bit 2 | `Snow_Ice` | 0 无、1 有 |
| bit 3 | `Aerosol` | 0 无／低、1 平均／高 |
| bit 4 | `Cirrus` | 0 无、1 有 |
| bit 5 | `Internal_CloudMask` | 0 无云、1 有云 |
| bit 6 | `Cloud_Shadow` | 0 无、1 有 |
| bit 7 | `SCF_Biome_Mask` | 0 biome 在指定区间外、1 在区间内；单独审计，不自动等同云污染 |

### 7.4 主掩膜与严格敏感性

主工程掩膜：

```text
lai_raw in [0,100]
AND FparLai_QC != 255
AND MODLAND_QC == 0
AND DeadDetector == 0
AND CloudState == 0
AND SCF_QC in [0,1]
AND FparExtra_QC != 255
AND LandSea in [0,1]
AND Snow_Ice == 0
AND Aerosol == 0
AND Cirrus == 0
AND Internal_CloudMask == 0
AND Cloud_Shadow == 0
```

Terra 与 Aqua 均可，`Sensor` 只用于分传感器审计。`SCF_Biome_Mask` 保存但不单独硬删。严格 Best-only 敏感性在主掩膜基础上要求 `SCF_QC==0`；不得因主结果不显著临时改用更宽 QC。

### 7.5 4 天到候、年到五年暴露

先在原生像元完成 QC 和比例转换。设第 `j` 个 4 天产品名义区间为 `I_j`，与候 `p` 的重叠天数为：

\[
o_{ijp}=|I_j\cap I_p|.
\]

原生像元候值：

\[
LAI_{ip}=\frac{\sum_j q_{ij}o_{ijp}LAI_{ij}}{\sum_j q_{ij}o_{ijp}}.
\]

分母为 0 则候值缺失。一个 4 天值跨两个候时按重叠天数分配权重，不把同一值复制成 4 个独立日观测。

对格点 `g` 年 `y` 的活跃候集合 `A_gy`，原生像元年生长季值为有效活跃候的等权平均：

\[
LAI_{iy}=\frac{\sum_{p\in A_{gy}}v_{ip}LAI_{ip}}{\sum_{p\in A_{gy}}v_{ip}}.
\]

原生时间覆盖率按有效观测重叠天数计算：

\[
T_{iy}=\frac{\sum_{p\in A_{gy}}\sum_j q_{ij}o_{ijp}}
{\sum_{p\in A_{gy}}n_p}.
\]

再空间聚合原生年值：

\[
LAI_{gy}=\frac{\sum_i A_{ig}v_{iy}LAI_{iy}}{\sum_i A_{ig}v_{iy}},
\quad C^{space}_{gy}=\frac{\sum_i A_{ig}v_{iy}}{A_g},
\]

\[
T_{gy}=\frac{\sum_i A_{ig}v_{iy}T_{iy}}{\sum_i A_{ig}v_{iy}}.
\]

要求 `Cspace≥0.70` 且 `Tgy≥0.70`，否则该 grid-year 缺失。活跃窗、覆盖阈值或 QC 改变时同步重算年值。

事件年 `y` 只使用 `y−5…y−1`：

\[
LAI_{base}=\frac{1}{5}\sum_{k=1}^{5}LAI_{g,y-k},
\]

\[
LAI_{trend}=\operatorname{median}_{1≤k<l≤5}
\frac{LAI_{g,y-l}-LAI_{g,y-k}}{l-k}.
\]

主分析要求 5／5 年有效；4／5 为敏感性。禁止事件年、事件后 LAI 和后值回填。MCD15A3H 从 2002-07-04 起，2002 不是完整年，因此五年主暴露从 2008 年事件起。

### 7.6 必过测试

**测试 L1：比例与缺测。** 原生 35→3.5；原生 249→缺失，不是 24.9。

**测试 L2：官方 QC 示例。** 十进制 64 的二进制为 `01000000`，`SCF_QC=2`，其余主字段为 0；它表示几何问题后备份算法，主掩膜排除。位顺序颠倒会得到错误结论。

**测试 L3：候权重。** 两个合格观测 LAI=2 和 4，与某候重叠 1 和 4 天，则候 LAI=`(2×1+4×4)/5=3.6`。

**测试 L4：五年无未来信息。** 2010 年事件只能使用 2005—2009；2002 部分年不能作为完整 2002 年值；不得使用 2010 或 2011 回填。

### 7.7 与课题匹配度

**匹配度高**：4 天观测比 16 天 NDVI 更适合候聚合，LAI 直接表达冠层结构，适合作为事件前五年背景暴露。  
**边界**：LAI 不是恢复结局，也不是事件识别指标；备份反演、云污染、2002 部分年和共享暴露簇必须显式处理；产品内反演不确定性不能靠空间重采样消除。

## 8. MOD13Q1.061 预处理 SOP

### 8.1 官方来源与下载字段

产品：16 天、250 m、MODIS Sinusoidal，2000-02-18 起。  
数据集 DOI：https://doi.org/10.5067/MODIS/MOD13Q1.061  
植被指数方法论文 DOI：https://doi.org/10.1016/S0034-4257(02)00096-2

| 原生 SDS | 类型 | 有效范围 | 缺测 | 比例因子 | 项目字段 |
|---|---|---:|---:|---:|---|
| `250m 16 days NDVI` | int16 | −2000—10000 | −3000 | 0.0001 | `ndvi_native`→`ndvi` |
| `250m 16 days pixel reliability` | int8 | 0—3 | −1 | 无 | `ndvi_reliability` |
| `250m 16 days VI Quality` | uint16 | 0—65534 | 65535 | 无 | `ndvi_vi_quality` |
| `250m 16 days composite day of the year` | int16 | 1—366 | −1 | 无 | `ndvi_composite_doy` |

### 8.2 `VI Quality` 位段

| 位段 | 名称 | 官方位值 |
|---|---|---|
| bits 0—1 | MODLAND QA | 0 好；1 已生产但需查其他 QA；2 很可能云；3 非云原因未生产 |
| bits 2—5 | VI Usefulness | 0 最高，至 12 最低；13 不可用、14 L1B 故障、15 其他原因未生产／不可用 |
| bits 6—7 | Aerosol Quantity | 0 气候态、1 低、2 中、3 高 |
| bit 8 | Adjacent cloud | 0 无、1 有 |
| bit 9 | Atmosphere BRDF Correction | 0 未做、1 已做；不是污染位 |
| bit 10 | Mixed Clouds | 0 无、1 有 |
| bits 11—13 | Land/Water Mask | 1 陆地、2 岸线／湖岸；其他为各类水体 |
| bit 14 | Possible snow/ice | 0 无、1 有 |
| bit 15 | Possible shadow | 0 无、1 有 |

`pixel reliability`：0 good、1 marginal、2 snow/ice、3 cloudy、−1 fill。

### 8.3 主掩膜与严格敏感性

```text
ndvi_raw in [-2000,10000]
AND reliability in [0,1]
AND VI_Quality != 65535
AND MODLAND_QA in [0,1]
AND VI_Usefulness <= 12
AND Aerosol_Quantity != 3
AND Adjacent_cloud == 0
AND Mixed_Clouds == 0
AND Land_Water_Mask in [1,2]
AND Possible_snow_ice == 0
AND Possible_shadow == 0
```

BRDF correction 位不作删除条件。严格 Best-only 敏感性要求 `reliability=0、MODLAND_QA=0、VI_Usefulness=0`，其余主污染条件不变。

### 8.4 16 天合成到候与年值

16 天 NDVI 是该合成期的代表值，不是 16 天日均，也不是 16 个独立日观测。主链采用与 LAI 相同的名义区间重叠加权：

\[
NDVI_{ip}=\frac{\sum_j q_{ij}o_{ijp}NDVI_{ij}}{\sum_j q_{ij}o_{ijp}},
\]

其中 `I_j` 为 16 天名义合成区间，`o_ijp` 为与候重叠天数。`composite day of the year` 用于检查实际入选日和像元间差异，不把整个 16 天值只放到该单日，也不把其复制成每日独立样本。

年活跃窗均值、时间／空间覆盖、五年基线和 Theil–Sen 斜率完全沿用第 7.5 节，只把 LAI 换为 NDVI。按既有协议，NDVI 五年暴露可从 2005 年事件起形成；但 2000 年仍须通过相同的活跃窗时间／空间覆盖检查，不能因产品在 2000-02-18 起有数据就自动宣称该日历年完整。与 LAI 的直接比较仍严格限于 2008—2023 共同事件、同窗口、同掩膜。

### 8.5 必过测试

**测试 N1：比例。** 原生 6500→0.65；−3000→缺失，不是 −0.3。

**测试 N2：位段。** 构造 QA：MODLAND=1、Usefulness=4、Aerosol=2、其余污染位为 0，则低 8 位为 `1+4×4+2×64=145`；解码应返回 `(1,4,2)`，主掩膜可保留。若 Aerosol=3 则排除。

**测试 N3：合成语义。** 一个 16 天 NDVI=0.6 不能展开为 16 行“独立日观测”；与两个候重叠 10 和 6 天时权重分别为 10、6。

**测试 N4：共同样本。** NDVI 单独五年模型可包含 2005—2007 事件；NDVI—LAI 对比模型不得包含这些年份。

### 8.6 与课题匹配度

**匹配度中等、定位清楚**：适合作为绿度指标稳健性，不适合替代 LAI 主暴露或证明冠层结构机制。  
**边界**：16 天合成的时间语义较粗；NDVI 饱和和冠层结构不等价；不得称为 LAI 真值验证。

## 9. MCD12Q2.061 动态物候预处理 SOP

### 9.1 官方来源与下载字段

产品：年度、500 m、MODIS Sinusoidal，2001 年起；按峰值所在日历年归集生长周期，最多提供两个周期的完整物候指标。  
数据集 DOI：https://doi.org/10.5067/MODIS/MCD12Q2.061  
官方算法依据：Gray、Sulla-Menashe & Friedl（2022）《User Guide to Collection 6.1 MODIS Land Cover Dynamics (MCD12Q2) Product》。该指南无独立论文 DOI；数据集 DOI 如上。不得将其他土地覆盖变化监理论文误作本产品算法论文。

| 原生 SDS | 类型 | 单位 | 有效范围 | 缺测 | 比例因子 | 用途 |
|---|---|---|---:|---:|---:|---|
| `Greenup` | int16 | days since 1970-01-01 | 11138—32766 | 32767 | 1 | 周期起点 |
| `Dormancy` | int16 | days since 1970-01-01 | 11138—32766 | 32767 | 1 | 周期终点 |
| `NumCycles` | int16 | 个数 | 1—7 | 32767 | 1 | 实际周期数审计 |
| `EVI_Amplitude` | int16 | NBAR-EVI2 | 0—10000 | 32767 | 0.0001 | 单周期展示 tie-break |
| `QA_Overall` | int16 | 类别 | 0—3 | 32767 | 1 | 主 QC |
| `QA_Detailed` | int16 | 位字段 | 0—16383 | 32767 | 1 | 分指标 QC 审计 |

实际 HDF4 中这些 SDS 可含 cycle 维。若导出工具展开为 `_1`、`_2`，统一映射成 `cycle_id=1/2`，不能当作两种不同变量。超过两个周期时，产品只保存 NBAR-EVI2 振幅最大的两个周期，但 `NumCycles` 可大于 2。

### 9.2 日期、周期与缺测

日期转换：

\[
date=1970\text{-}01\text{-}01+native\_days.
\]

例如 11138→2000-06-30。不得把该整数当作年内 DOY。

主 QC：`QA_Overall∈{0,1}`（best／good），且同一 cycle 的 Greenup、Dormancy 均有效。`QA_Detailed` 逐指标保存；主方案不再额外硬删 detailed=fair，以避免改变既有样本域，Best-only 与纳入 Fair 的总体 QC 均作独立敏感性。

`QA_Detailed` 的七个 2 位字段顺序为 Greenup、MidGreenup、Maturity、Peak、Senescence、MidGreendown、Dormancy：

```text
qa_greenup       = (QA_Detailed >> 0)  & 3
qa_midgreenup    = (QA_Detailed >> 2)  & 3
qa_maturity      = (QA_Detailed >> 4)  & 3
qa_peak          = (QA_Detailed >> 6)  & 3
qa_senescence    = (QA_Detailed >> 8)  & 3
qa_midgreendown  = (QA_Detailed >> 10) & 3
qa_dormancy      = (QA_Detailed >> 12) & 3
```

位值 0、1、2、3 分别为 best、good、fair、poor。

### 9.3 原生像元到格点动态窗

对每个 `grid_id×year×cycle_id`，收集 QC 合格且日期完整的原生像元。以交叠面积为权重，分别在绝对 Epoch 日期上计算加权中位数：

\[
G_{gyk}=weighted\_median_i(Greenup_{iyk};A_{ig}),
\]
\[
D_{gyk}=weighted\_median_i(Dormancy_{iyk};A_{ig}).
\]

要求 `D≥G`，否则该 cycle 进入异常审计且不生成区间。每个有效 cycle 形成 `[G,D]`，多周期取日期区间并集，重叠日只计一次。不得分别对年内 DOY 做普通算术平均，因为周期可跨年。

当年采用动态窗的条件沿用协议：有效原生面积≥0.50、有效原生像元≥30；不足则回退到该格点全部有效年份的 SOS／EOS 中位数。2000 年也回退；有效物候年份<5 时主分析物候缺失。逐年窗与回退标记写入 `grid_phenology_year` 和 `grid_phenology_segment`。

活跃候规则：某候与任一有效物候区间至少重叠 1 个日历日，则 `active_flag=1`；同时保存重叠天数。`active_window_length_L` 为该 grid-year 的活跃候数，多周期并集不得重复计数。事件资格、L 和植被年合成必须使用同一 `phenology_mode` 版本。

### 9.4 产品内处理与本项目回填的边界

MCD12Q2 算法会使用产品年及前后年的 NBAR-EVI2，并可能用前后年好质量值填补缺测。这是官方产品内算法，不得误写成“本项目用后值回填 LAI”。但它也意味着动态物候不是严格逐年独立估计；固定 4—9 月和气候态物候敏感性用于检验这一依赖。

### 9.5 必过测试

**测试 P1：官方 QA 解码。** 下列输入必须得到官方七维向量：

| `QA_Detailed` | 期望输出：Greenup 至 Dormancy |
|---:|---|
| 0 | `[0,0,0,0,0,0,0]` |
| 5461 | `[1,1,1,1,1,1,1]` |
| 15963 | `[3,2,1,1,2,3,3]` |
| 14409 | `[1,2,0,1,0,2,3]` |
| 16383 | `[3,3,3,3,3,3,3]` |

**测试 P2：跨年。** Greenup=上年 12 月 20 日、Dormancy=产品年 4 月 10 日，转换后区间连续；若先把二者变成 DOY 再要求 Dormancy>Greenup，会错误删除该周期。

**测试 P3：多周期并集。** 区间 `[3月1日,5月31日]` 与 `[7月1日,9月30日]` 形成两个活跃段；6 月不因两区间端点取总最小／最大而被错误纳入。

### 9.6 与课题匹配度

**匹配度中高**：比固定 4—9 月更能适应黄土高原空间物候差异，可统一事件资格与生长季 LAI。  
**边界**：产品是模型化物候，不是逐年实测；跨年、多周期、产品内相邻年依赖和回退样本必须审计，不能把动态选择当作无代价改进。

## 10. MCD12Q1.061 土地覆盖预处理 SOP

### 10.1 官方来源与下载字段

产品：年度、500 m、MODIS Sinusoidal，2001 年起。  
数据集 DOI：https://doi.org/10.5067/MODIS/MCD12Q1.061  
C6 算法论文 DOI：https://doi.org/10.1016/j.rse.2018.12.013

| 原生 SDS | 类型 | 有效范围 | 缺测 | 项目字段 | 用途 |
|---|---|---:|---:|---|---|
| `LC_Type1` | uint8 | 1—17 | 255 | `igbp_code` | 年度 IGBP 地类 |
| `QC` | uint8 | 0—10 | 255 | `landcover_qc` | 分类状态 |
| `LW` | uint8 | 1—2 | 255 | `land_water_flag` | 1 水、2 陆地 |
| `LC_Prop1_Assessment`（仅审计） | uint8 | 0—100 | 255 | `lccs1_confidence` | LCCS1 置信度，不是 IGBP 置信度 |

官方原生字段是 `QC`，不是 `LC_QC`。M1 必须按此映射。

### 10.2 IGBP 映射与 QC

协议保留 IGBP `[1,2,3,4,5,6,7,8,9,10,12,14]`，排除 11 湿地、13 城市、15 雪冰、16 裸地和 17 水体。

模型四类映射：

| 项目地类 | IGBP |
|---|---|
| `forest` | 1—5 |
| `grassland` | 6—10；其中包括灌木、稀树草原和草地，名称不缩写成纯草地实测 |
| `cropland` | 12、14 |
| `other` | 其他进入模型但不属于上述三类的有效陆地；主静态掩膜仍排除 11、13、15、16、17 |

`QC` 官方类别包括：0 已分类陆地、1 未分类陆地、2 已分类水体、3 未分类水体、4 海冰处理、5 水体误分类后改标签、6 雪冰补标、7 雪冰误分类后改裸地、8 稳定化缺标签后回填、9 气候规则改变森林类型、10 无数据。

主处理要求 `LW=2`、`LC_Type1` 有效且 `QC` 非 1／3／10／255；随后仍按 IGBP 保留类筛选。QC=8／9 保留并打标，QC=0-only 为严格敏感性。不得把 `LC_Prop1_Assessment` 当作 `LC_Type1` 的后验概率。

### 10.3 年度空间聚合与静态掩膜

逐年计算 IGBP 类别面积比例 `f_gky` 和四类面积比例。年度主地类取比例最大者，并保存 `dominant_class_frac`；并列时按 IGBP 编码较小者确定性处理，同时打 `tie_flag`，不得随机选择。

静态掩膜沿用 M3：有效记录≥10 年、原生排除类面积比例≥0.80 时永久排除、格点植被面积≥0.50。逐年地类只作协变量／分层，不用每年类别变化硬删事件；无地类掩膜为独立敏感性。

官方明确警告不宜用该产品直接判断分类后土地覆盖变化。因此，本项目不把 2001—2023 年标签逐年跳变直接命名为退耕还林或真实土地转化。

### 10.4 必过测试

**测试 T1：类别不能平均。** 两个等面积像元 IGBP=1 和 10，正确输出森林 0.5、grassland 0.5；输出类别 5.5 为失败。

**测试 T2：置信层不可错配。** `LC_Prop1_Assessment=80` 不能写成“IGBP LC_Type1 置信度 80%”。

**测试 T3：面积并列。** 两类各 0.5 时保存 tie_flag，并按确定性规则选主类；多次运行结果一致。

### 10.5 与课题匹配度

**匹配度中等**：适合静态土地掩膜、地类协变量和分层标准化。  
**边界**：500 m 混合像元和年际分类不稳定明显；2021 年及以后训练库代表性需额外谨慎；不承担土地覆盖变化检测或因果识别。

## 11. SoilGrids250m 预处理 SOP

### 11.1 官方来源、下载层与版本

官方来源：ISRIC SoilGrids；主属性为砂粒和黏粒的 0—5、5—15、15—30 cm `mean` 层。  
SoilGrids250m 论文 DOI：https://doi.org/10.1371/journal.pone.0169748  
SoilGrids 2.0 不确定性论文 DOI：https://doi.org/10.5194/soil-7-217-2021

覆盖 ID：

```text
sand_0-5cm_mean, sand_5-15cm_mean, sand_15-30cm_mean
clay_0-5cm_mean, clay_5-15cm_mean, clay_15-30cm_mean
```

可选 `silt` 同深度层只用于砂／粉／黏闭合 QC，不进入主模型。SoilGrids 是滚动发布资源，不能只写“250 m 版”而不保存下载日期、请求 URL、覆盖 ID、文件哈希和元数据版本。

### 11.2 原生单位、投影和缺测

- `sand`／`clay` mapped units：g/kg；原生整型值除以 10 得 g/100g，即质量百分比；
- 原生 VRT：Interrupted Goode Homolosine、WGS84、250 m；
- 原生 VRT `NoDataValue=-32768`，数据类型 Int16；
- WCS 请求若指定 `outputCRS=EPSG:4326`，所得文件是重投影服务输出，不得称为原生 Homolosine 文件；
- 原生无逐像元 QC 位段，不确定性分位数不能当作 QC bit。

本次实际证据：

| 证据 | 实测内容 |
|---|---|
| WCS 样例 | `clay_0-5cm_mean`，107.0—107.1°E、37.0—37.1°N，EPSG:4326 输出 |
| 数组 | 42×44、int16，原生数值 139—216，均值 176.030844 |
| 物理单位 | 对应约 13.9%—21.6%黏粒，均值约 17.603% |
| WCS SHA256 | `ddf643fc8a88691280b5b6172b1011ad7a2c81c18a50adde4279e717cf9e0d2b` |
| 原生 VRT | 250 m、Homolosine、NoData −32768 |
| VRT SHA256 | `ad1a77d56090bf543e3600bc48d4cd6fa80f8e1a9eb37177044de65a64848ede` |

WCS 小样例没有 GDAL_NODATA 标签，因此原生 NoData 以 VRT 为证据，不能从该 WCS 子集反推所有输出都带缺测标签。

### 11.3 0—30 cm 厚度加权

在原生像元先完成单位转换和三层完整性检查：

\[
x_{0-30}=\frac{5x_{0-5}+10x_{5-15}+15x_{15-30}}{30},
\]

其中 `x` 为 sand 或 clay 的质量百分比。三层必须全部有效；不得缺一层后把分母改成剩余厚度并假装等价。可选闭合检查为 `sand+silt+clay≈100%`，偏差只作产品不确定性审计，不逐像元强制归一化到 100%。

### 11.4 空间聚合

厚度合成后再按第 3 节面积加权到 0.1°：

\[
x_{g,0-30}=\frac{\sum_i q_iA_{ig}x_{i,0-30}}{\sum_i q_iA_{ig}}.
\]

主覆盖阈值 0.70。模型前再按分析样本 1 SD 标准化，同时保存原始百分比。不能把 SoilGrids 当成逐格点实测土壤，也不能用高分辨率外观忽略数字土壤制图不确定性。

### 11.5 必过测试

**测试 S1：单位。** 原生 176 g/kg→17.6%，不是 176% 或 1.76%。

**测试 S2：层厚。** 三层砂粒为 100、200、300 g/kg，则 0—30 cm 为 `(5×100+10×200+15×300)/30=233.333… g/kg`，即 23.333…%。

**测试 S3：缺层。** 若 15—30 cm 为 −32768，则 0—30 cm 为空，不用 0—15 cm 均值代替。

**测试 S4：投影声明。** 本次 WCS EPSG:4326 样例通过坐标和值域验收，但报告必须写“WCS 重投影样例”，不能写“原生投影 GeoTIFF”。

### 11.6 与课题匹配度

**匹配度中等**：适合静态土壤质地控制和分层，支撑 LAI×深层水关联中的背景差异调整。  
**边界**：预测土壤图有空间不确定性；静态协变量不证明土壤—深层水因果机制，也不宜把区域预测不确定性压缩成单一确定值后不作说明。

## 12. NASADEM_HGT.001 预处理 SOP

### 12.1 官方来源与原生文件

产品：1 arc-second、1°×1°瓦片，约 30 m。  
数据集 DOI：https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001

| 文件层 | 类型 | 单位／含义 | 官方 Fill／NoData | 有效范围 |
|---|---|---|---|---:|
| `hgt` | 2-byte signed integer、大端序 | m，相对 EGM96 大地水准面 | N/A | −32767—32767 |
| `num` | unsigned byte | 数据来源／处理类别 | N/A | 0—255 |

每个瓦片 3601×3601，文件名坐标表示西南角，例如 `NASADEM_HGT_n37e107.zip`。相邻瓦片边界有重叠行列，镶嵌时必须去重，不能把重叠边重复加权。

 merged HGT 与 SRTM-only 浮点高程的垂直基准不同：本项目只使用 merged HGT 的 EGM96 高程，不与 WGS84 椭球高直接混用。

### 12.2 缺测、来源与物理检查

- merged HGT 官方表未给统一 NoData；实文件仍须检查元数据和物理异常；
- `NUM=255` 表示 ERROR，主分析排除；NUM=0 为水体，NUM=250 为插值，其他区间对应 SRTM、GDEM、NED 等来源；
- 填充来源不等于自动无效，但必须保存 `num` 面积比例，以便说明地形值中有多少来自次级 DEM／插值；
- 对研究区高程做合理范围和突变审计，不把官方 int16 的全部理论范围当成当地合理高程。

### 12.3 原生坡度派生

主方案在原生高程网格上采用与 NASADEM 官方思路一致的 3×3 局部二次曲面，但不冒称完全复制官方坡度产品：

1. 以目标 posting 为中心，将 3×3 邻域从经纬度转至局部 East–North–Up 米制坐标；东西向距离随纬度变化，不能直接用角度当米；
2. 拟合
   \[
   z=p_0x^2+p_1xy+p_2y^2+p_3x+p_4y+p_5;
   \]
3. 因仅下载 HGT＋NUM、没有官方高度误差权重场，主实现使用有效邻点等权，并记录 `slope_method=nasadem_quadric_3x3_unweighted_enu`；
4. 中心梯度 `f_x=p_3、f_y=p_4`，坡度角为
   \[
   slope\_deg=\arctan\sqrt{f_x^2+f_y^2}\times180/\pi.
   \]

邻域有效点不足或拟合矩阵奇异时坡度为空。瓦片边缘必须读取相邻瓦片邻域，不能在每块边界强行缩小窗口造成边缘条带。

### 12.4 空间聚合

高程和原生坡度分别面积聚合至 0.1°：

\[
elev_g=\frac{\sum_i q_iA_{ig}elev_i}{\sum_i q_iA_{ig}},\qquad
slope_g=\frac{\sum_i q_iA_{ig}slope_i}{\sum_i q_iA_{ig}}.
\]

不能先把高程平均到 0.1°再从粗高程求坡度；坡度是非线性局部派生量，两种顺序不等价。主覆盖阈值 0.70，并保存 NUM 来源比例。

### 12.5 必过测试

**测试 D1：字节与尺寸。** 3601×3601 的 int16 大端数组应正确读取；若高程出现系统性极端异常，首先检查字节序，不做缩尾掩盖。

**测试 D2：平面坡度。** 对 `z=ax+by+c`，二次拟合应恢复 `f_x=a、f_y=b`；`a=b=0` 时坡度 0°，`a=1、b=0` 时坡度 45°。

**测试 D3：垂直基准。** merged HGT 标记 EGM96；不得与 SRTM-only WGS84 椭球高无转换拼接。

**测试 D4：瓦片边缘。** 同一平面跨两个瓦片时，边界坡度与内部一致；不能出现伪零坡或异常突变。

### 12.6 与课题匹配度

**匹配度中等**：高程与坡度是合理的静态地形控制，可减少地形与气候、土壤水之间的混杂。  
**边界**：雷达高程受植被和填充来源影响；派生坡度不是官方 NASADEM 坡度产品的逐位复刻；地形协变量不构成因果识别。


## 13. 可选 ERA5 环流诊断预处理 SOP

### 13.1 角色、入口与放行状态

环流只用于解释 F_R、F_Z、P\F、F\P 事件附近的天气尺度背景，不进入 SMP 识别、恢复定义、LAI 暴露或主模型。官方入口为 CDS 的 ERA5 小时单层和压力层产品；启用前必须完成 M1 实文件验收。

- ERA5 方法论文 DOI：https://doi.org/10.1002/qj.3803
- ERA5 小时单层数据集 DOI：https://doi.org/10.24381/cds.adbb2d47
- ERA5 小时压力层数据集 DOI：https://doi.org/10.24381/cds.bd0915c6

本附录给出启用后的执行契约，但不追溯改变既有工作包中“可选环流暂时锁定”的状态。只有字段、单位、时间戳、压力层和实文件哈希均验收后，才可在该 `run_id` 内标为 `conditional_frozen`；否则删除该诊断，不影响路线一。

### 13.2 下载字段、单位与规范变量

| CDS 原生变量名 | 短名 | 层／类型 | 原生单位 | 规范字段 | 转换 |
|---|---|---|---|---|---|
| `geopotential` | `z` | 500 hPa、瞬时 | m² s⁻² | `z500_m2s2`→`z500_gpm` | 除以 `g0=9.80665 m s⁻²` |
| `u_component_of_wind` | `u` | 700、850 hPa、瞬时 | m s⁻¹ | `u700`、`u850` | 不换算 |
| `v_component_of_wind` | `v` | 700、850 hPa、瞬时 | m s⁻¹ | `v700`、`v850` | 不换算 |
| `specific_humidity` | `q` | 700、850 hPa、瞬时 | kg kg⁻¹ | `q700`、`q850` | 不换算；不当作 kg/m³ |
| `vertical_integral_of_eastward_water_vapour_flux` | `viwve` | 单层、瞬时积分量 | kg m⁻¹ s⁻¹ | `ivt_u` | 不换算 |
| `vertical_integral_of_northward_water_vapour_flux` | `viwvn` | 单层、瞬时积分量 | kg m⁻¹ s⁻¹ | `ivt_v` | 不换算 |

主实现直接下载两个官方整层水汽输送分量，避免自行选择积分上下限造成额外版本差异。`q700／q850` 用于低层湿度诊断，不能替代整层 IVT。若另行从压力层重算 IVT，只能作为登记后的敏感性：

\[
IVT_u=-\frac1g\int q\,u\,dp,\qquad IVT_v=-\frac1g\int q\,v\,dp,
\]

其中 `dp` 用 Pa，积分方向和上下限必须写入元数据；低于地面的压力层不得填 0 后纳入。直接下载量与自行积分量的差异不得混作同一变量。

### 13.3 缺测、时间与空间聚合

1. 无 MODIS 式 QC 位段；NetCDF 按实际 `_FillValue`／`missing_value`、比例和偏移属性解码，GRIB 按缺测位图处理。
2. 所有瞬时字段先保留 UTC 小时值。可选环流采用严格的日完整性：当日 00—23 UTC 共 24 个时次齐全才计算日均；不得用四个时次冒称与 24 小时日均等价。
3. 日值到候按第 2 节状态量规则：至少 4 个有效日且连续缺失不超过 2 天。
4. `z500_gpm` 在小时值完成重力换算后平均；`u／v／q／ivt_u／ivt_v` 直接求算术平均。
5. IVT 先分别平均分量，再计算合成向量的模：
   \[
   \overline{IVT}=\sqrt{\overline{IVT_u}^2+\overline{IVT_v}^2}.
   \]
   若另需“逐时 IVT 模的候均值”，必须另存 `ivt_magnitude_mean`，不得与上式混名。
6. 连续场在原生网格完成时间聚合后，按真实交叠面积聚合到目标网格；风和 IVT 均先聚合分量，不直接平均方向角或模。重网格不增加环流信息。

### 13.4 必过测试

**测试 R1：位势高度。** `z=49033.25 m² s⁻²` 时，`z500_gpm=5000`；不得直接以 m 或 gpm 重复除重力。

**测试 R2：向量模。** 候均 `ivt_u=300、ivt_v=400 kg m⁻¹ s⁻¹` 时，合成模为 500；它不是逐时模均值，字段和图注须写清。

**测试 R3：日均完整性。** 某日只有 00、06、12、18 UTC 四个时次，即使数值正常，主可选诊断的日均仍为空并记 `incomplete_hourly_day`。

**测试 R4：比湿单位。** `q850=0.008 kg kg⁻¹` 保持 0.008；不乘 1000 后仍标 kg/kg，也不把该值当作整层水汽。

### 13.5 与课题匹配度

**匹配度中低、仅作条件性诊断**：500 hPa 高度、低层风湿和 IVT 可帮助判断湿急转是否具有可解释的天气尺度背景。  
**边界**：ERA5 与 ERA5-Land 同属再分析体系，不能充当独立真值；事件数 `n<20` 只展示案例，`20≤n<30` 仅探索，`n≥30` 且空间块≥10 才给块区间。合成图一致不等于证明 F_R 的因果机制。

## 14. 站点数据与研究区矢量验收 SOP

### 14.1 为什么这两项只给验收契约

站点清单、使用权和研究区矢量尚未正式冻结，本附录不虚构网络名称、站数、站点记录或边界来源。二者采用“先验收、后放行”的状态门：站点不足不阻塞主链，但不能声称已完成独立站点验证；研究区矢量未冻结时不得生成正式区域结果。

### 14.2 站点原始清单与字段

`metadata/station_metadata.csv` 至少包含：

```text
source_id, network_name, station_id_native, station_id,
station_name, lon, lat, crs, elevation_m, elevation_datum,
variable_type, variable_name_native, depth_top_cm, depth_bottom_cm,
unit_native, fill_value_native, qc_scheme_native, qc_flag_native,
timezone, utc_offset, daylight_saving_rule, day_definition,
timestamp_start, timestamp_end, temporal_resolution,
access_permission, license, official_url, download_time_utc,
file_sha256, chirps_fusion_status, independent_holdout_flag,
acceptance_status, exclusion_reason, notes
```

站点长表另存原始值和原始质量标记，不只保留转换后的值：

```text
station_id, timestamp_native, timestamp_utc, timestamp_local,
variable_type, value_native, unit_native, qc_flag_native,
depth_top_cm, depth_bottom_cm, sm_value, sm_unit,
p_value, p_unit, qc_keep, missing_reason, source_file_sha256
```

放行条件：

- 经纬度 CRS、站点海拔基准、观测层深、原时制、日界、单位、缺测码和 QC 含义均有来源依据；
- 使用权限允许本课题处理和汇总；论文只公开许可范围内的站点信息；
- 时间戳唯一性或重复处理状态明确，站点迁址／仪器更换另建分段记录，不静默拼接为同质长序列；
- `independent_holdout_flag=true` 必须有未进入目标产品融合或严格留出的证据。CHIRPS 已融合站点只能做一致性检查。

### 14.3 土壤水站：单位、层深和日／候处理

1. 体积含水率 `θ` 的规范单位为 m³/m³。只有元数据明确为百分数时才执行 `θ=θ_percent/100`；不得凭数值在 0—100 之间猜单位。
2. 某层厚度为 `Δz` m 时，可另算该传感器代表层的水量当量：
   \[
   S_{station}=1000\,\theta\,\Delta z\quad[mm].
   \]
   该值不代表完整 0—100 cm 储量。只有传感器层完整覆盖目标土柱且无缺层时才可求层和；离散深层传感器不得外推整个剖面。
3. 站点与产品层深不一致时，主比较使用各自长期序列内的距平、百分位和相位；不直接以绝对 mm 偏差评价“谁更准确”。
4. 亚日状态值按站点原生日定义形成日均并保存期望／有效时次；原生日值不人为拆成小时。日值到候沿用至少 4 个有效日、连续缺失不超过 2 天规则。
5. 只有具备亚日时间戳和时区时才转换为 UTC 日；仅有日期且日界未知时保留原生日并标 `day_boundary_unknown`，不得按猜测平移 8 小时。
6. 匹配主所在格点，3×3 邻域为敏感性；站点是点观测，不能像栅格一样做面积平均。

### 14.4 降水站：区间总量、时制与湿候匹配

1. 原生降水可为某观测区间的 mm 总量或速率。总量直接累加；速率必须乘其实际区间秒数并依元数据转换，不能一律乘 86400。
2. 亚日记录先按站点官方日界求日总量，要求组成区间完整；原生日总量不再差分，也不重复乘 24。
3. 日值到候要求全部日记录有效，任一日缺测则候总量为空。第 73 候保留真实 5／6 天总量，日速率和 5 天等价量只作敏感性。
4. 土壤水站与降水站分轨：降水站只校验 P、P95 湿候和日期，不能替代 SMP 验证；土壤水站也不能用于证明 CHIRPS 降水准确。
5. 汇总误差只有在至少 5 站、30 个匹配事件、50 个有效站点—候配对同时满足时计算；不足只列个案并写 `insufficient_support`。

### 14.5 重复、缺测、异常与禁止反演调参

- **完全重复**：同一 `station_id×timestamp×depth×variable` 的原值、单位和 QC 完全相同，可保留一条并记录重复数。
- **冲突重复**：同键数值不同，不取均值；标为 `conflicting_duplicate` 并排除该键，除非来源方给出明确修订优先级。
- **缺测**：原生填充值和 QC 不合格值转为空值加原因；不得改为 0。降水“无降水”与“无观测”必须分开。
- **异常**：物理范围检查只标记或按预先规则排除，不因站点与产品不一致而删站、改层深、改时区或调整事件阈值。
- **验证未达期望**：依次检查时制、层深和空间代表性，再降级为相位／异常描述；不得反演调整主分析参数。

### 14.6 研究区矢量：几何、坐标和面积验收

研究区文件在 M0／M1 登记 `metadata/study_area_manifest.csv`，至少包含：

```text
boundary_id, definition_version, publisher, official_url,
license, download_time_utc, file_name, file_sha256,
source_crs, geometry_type, feature_count, validity_status,
bbox, area_km2_equal_area, dissolve_rule, repair_rule,
inclusion_rule, acceptance_status, notes
```

处理规则：

1. 原始矢量只读保存并计算哈希；存储 CRS、原始发布日期／版本、许可和下载入口必须明确。
2. 检查空几何、自相交、重复环、重复要素和跨区碎片。几何修复只修正拓扑错误，不借修复改变行政或自然区划定义；所有修复写入日志。
3. 若研究区由多要素组成，按预先登记的 `inclusion_rule` 选择并融合；不得看结果后增删子区。面积在合适等面积投影或球面几何计算，经纬度坐标下不直接用平面度数面积。
4. 研究区裁剪保留真实边界交叠面积；外包矩形只能用于下载，不能替代正式研究区掩膜。
5. 冻结输出 `data/frozen/{run_id}/study_area.gpkg` 和 `grid_manifest.parquet`；每个格点保存研究区面积、目标格点总面积和面积比例。矢量变化触发空间重跑，不自动改变科学参数。

### 14.7 必过测试

**测试 V1：百分比单位。** 元数据为体积含水率百分数、原值 25 时，规范 `θ=0.25 m³/m³`；若元数据已是 m³/m³，则原值 0.25 不再除 100。

**测试 V2：层厚与不可外推。** `θ=0.25`、代表层厚 0.20 m 时，该层水量当量 50 mm；单个 100—120 cm 传感器不能被写成完整 0—100 cm 或 100—289 cm 储量。

**测试 V3：重复记录。** 同键同值重复去重并留痕；同键 0.20 与 0.35 的冲突记录不得自动平均为 0.275。

**测试 V4：降水完整性。** 平年某候日值为 `[2,0,1,缺失,3] mm`，候 P 为空，不是 6 mm。

**测试 V5：几何与面积。** 人为构造自相交多边形必须被检出；修复前后面积变化写入报告。下载外包矩形面积不得代替正式研究区面积。


## 15. 跨产品测试矩阵、接口与机器可读输出

### 15.1 统一测试矩阵

下表是最低测试集，不替代第 4—14 节的数值细节。`P` 状态产品仍应先跑合成单元测试；实文件到位后再跑原生文件验收，两者不能互相替代。

| 测试 ID | 对象 | 必须证明的性质 | 失败处置 |
|---|---|---|---|
| U1 | 73 候日历 | 平年 365 天、闰年 366 天；73 段无重叠、无空洞；跨年 `t_abs` 连续 | 停止全部事件生产 |
| U2 | 状态量完整性 | 候均至少 4 有效日；连续缺失>2 天即空；有效日权重正确 | 对应格点—候置空并审计 |
| U3 | 通量完整性 | 任一组成日缺失则候总量为空；第 73 候真实 5／6 天总量正确 | 不得跳过缺日后求和 |
| U4 | 面积加权 | 交叠面积而非像元数决定权重；有效面积<0.70 输出空；区域总水量守恒 | 停止空间聚合并退回 |
| U5 | 类别聚合 | 保存面积比例，不平均类别编号；并列规则确定且留 `tie_flag` | 停止掩膜／地类生产 |
| E1—E4 | ERA5-Land | 日界、小时增量、蒸发符号、层厚和闰年第 73 候正确 | 停止 ERA5-Land 主链 |
| G1—G4 | GLDAS | `_tavg` 乘区间秒数、`_acc` 不重复乘秒、0—100 cm 求和、B 符号正确 | 停止 GLDAS 主链 |
| C1—C4 | CHIRPS | `precip` 的 mm/day 语义、缺测完整性、近零值和第 73 候正确 | 停止 CHIRPS 敏感性批次 |
| L1—L4 | MCD15A3H | 0.1 比例、249—255 排除、QC 位段、4 天权重和五年无未来信息 | 停止 LAI 暴露生产 |
| N1—N4 | MOD13Q1 | 0.0001 比例、QC 位段、16 天合成语义和共同样本年份正确 | 停止 NDVI 稳健性，不改主 LAI |
| P1—P3 | MCD12Q2 | 官方 QA 向量、绝对日期跨年、多周期并集正确 | 回退规则仍须验证；失败则物候主链停止 |
| T1—T3 | MCD12Q1 | 类别比例、置信层语义和并列确定性正确 | 停止地类／掩膜生产 |
| S1—S4 | SoilGrids | g/kg 转百分比、层厚、缺层为空、WCS 与原生投影证据不混写 | 静态协变量置空并停止相关模型 |
| D1—D4 | NASADEM | 大端序、尺寸、垂直基准、平面坡度和瓦片边缘正确 | 停止地形协变量生产 |
| R1—R4 | 可选 ERA5 环流 | 位势高度、IVT 分量／模、24 时次完整性和比湿单位正确 | 删除可选诊断，不影响主链 |
| V1—V5 | 站点／研究区 | 单位、层深、重复、通量完整性和几何面积正确 | 站点降级或不放行；矢量失败则无正式区域结果 |

状态量完整性的具体测试：闰年第 73 候 6 天中，第 2—3 天缺测、其余 4 天有效，可求候均；若连续缺测 3 天，即使其他 3 天有效，也必须为空。平年 5 天候只有 3 个有效日时同样为空。

每条测试写入 `outputs/{run_id}/reports/sop_unit_test_result.csv`：

```text
test_id, product_code, test_layer, fixture_id, fixture_sha256,
expected_value, observed_value, tolerance, pass,
code_sha256, params_sha256, run_id, executed_at_utc, notes
```

`test_layer` 受控取值为 `synthetic_unit`、`native_file_acceptance`、`integration`。不得用 `skip` 冒充 `pass`；不适用必须写 `not_applicable` 和原因。

### 15.2 M1／M2／M3／M6／M9 接口对应

| 模块 | 本附录输入契约 | 既有冻结输出 | 本附录补充的验收输出 |
|---|---|---|---|
| M1 | 原生文件、官方元数据、下载请求、权限和版本 | `source_file_manifest.csv`、`source_variable_map.csv`、`station_metadata.csv`、条件性 `circulation_variable_map.csv` | `sop_native_acceptance.csv`、`sop_product_coverage.csv`、`study_area_manifest.csv` |
| M2 | M1 已放行变量映射、原生 QC 和缺测 | `time_pentad_calendar.parquet`、`grid_day_{product_code}.parquet`、`grid_pentad_base_{product_code}.parquet`、`grid_static_covariates.parquet` | `sop_unit_test_result.csv`，并沿用既有累计、符号、面积和第 73 候报告 |
| M3 | MCD12Q1／Q2 原生类别和 QA、M2 物理量、研究区 | `grid_mask.parquet`、`grid_phenology_year.parquet`、`grid_phenology_segment.parquet`、`grid_active_pentad.parquet`、`grid_climatology_*.parquet`、`grid_pentad_*.parquet` | 物候回退、掩膜选择和气候态支撑沿用既有报告，不另建平行版本 |
| M6 | 原生 QC 后的 LAI／NDVI、活跃窗、深层水、事件骨架 | `vegetation_grid_year_lai.parquet`、`vegetation_grid_year_ndvi.parquet`、`event_exposure.parquet`、`exposure_cluster_*.parquet` | 年覆盖和五年窗不足原因必须写入年表／偏离日志 |
| M9 | 站点长表与元数据、可选 ERA5 环流、四套冻结产品 | `station_sm_validation.csv`、`station_p_validation.csv`、`station_case_audit.csv`、条件性 `circulation_composite.csv` | 未达样本或权限门槛时写 `conditional_skipped` 及原因 |
| M10 | 全部清单、测试、参数、代码和冻结表 | `review_*.csv`、`sample_flow.csv`、`result_manifest.json` | 汇总 D／F／P 证据状态，禁止把 P 写成 F |

`sop_native_acceptance.csv` 至少包含：

```text
source_id, file_sha256, product_code, collection,
variable_check, dimension_check, coordinate_check, time_check,
unit_check, fill_check, qc_decode_check, physical_range_check,
acceptance_status, failed_items, reviewer, accepted_at_utc
```

`sop_product_coverage.csv` 至少包含：

```text
product_code, year, n_source_files_expected, n_source_files_received,
n_days_expected, n_days_valid, n_pentads_expected, n_pentads_valid,
spatial_area_expected_km2, spatial_area_valid_km2,
missing_periods, duplicate_periods, coverage_status
```

### 15.3 已取得实文件的证据登记

| 产品 | 实际样例 | 验收结果 | SHA256 |
|---|---|---|---|
| CHIRPS v2.0 | NOAA ERDDAP 官方镜像 NetCDF；2020-06-01—02；107.0—107.1°E、37.0—37.1°N；2×3×2 | `precip`、float32、mm/day、−9999 缺测、日开始时间和近零值已读通；不是 UCSB 原生日文件验收 | `287c36f28375d8ef37c3dd37ccf08974cdddb131c995f106c5660fdda1e5b521` |
| SoilGrids clay 0—5 cm mean | 官方 WCS 小区域 GeoTIFF；42×44、int16；EPSG:4326 | 原值 139—216，均值约 176.030844 g/kg；这是 WCS 重投影样例 | `ddf643fc8a88691280b5b6172b1011ad7a2c81c18a50adde4279e717cf9e0d2b` |
| SoilGrids 原生 VRT | 官方原生 VRT 元数据 | Interrupted Goode Homolosine、WGS84、250 m、Int16、NoData−32768 已核验 | `ad1a77d56090bf543e3600bc48d4cd6fa80f8e1a9eb37177044de65a64848ede` |

其余需要 CDS／Earthdata 权限或尚未取得瓦片的产品保持 P。不得因合成测试通过而把其 `evidence_level` 改为 F。

### 15.4 跨产品处理不变量

1. ERA5-Land、GLDAS 和 CHIRPS 各自形成 P 序列并独立估计 P95；不得把一套产品的阈值套到另一套。
2. ERA5-Land／GLDAS 各自形成 SMP、W 和深层水百分位；CHIRPS 只替换降水，不提供 SMP 或深层水。
3. 四套组合为 ERA5／ERA5、GLDAS／GLDAS、ERA5／CHIRPS、GLDAS／CHIRPS；产品替换后事件、恢复和分支完整重算，不拼接已有结局。
4. GLDAS 原生 0.25°结果与 0.1°重网格结果分版保存；后者行数增加不等于独立信息增加。
5. LAI 和 NDVI 的原生 QC 在重网格前完成；年度合成均要求时间、空间覆盖≥0.70；NDVI 不作为 LAI 的替代真值。
6. 所有缺失、排除和未知状态进入样本流，不能以 0、−9999 或阴性结局悄悄填回。

## 16. 冻结状态、放行门槛与变更触发器

### 16.1 本附录正式固定的实现规则

以下内容可直接进入代码审查，不依赖结果方向：

- 原始文件只读、哈希、版本、变量映射和空值原因完整；
- 原生 QC→比例／单位／符号→原生分辨率时间聚合→垂直层合成→面积聚合→年生长季和五年暴露的顺序；
- 73 候日历、跨年时间轴、状态量与通量完整性、第 73 候真实总量；
- 真实交叠面积、主空间覆盖 0.70、0.50／0.85 独立敏感性和类别面积比例；
- ERA5-Land、GLDAS、CHIRPS、MCD15A3H、MOD13Q1、MCD12Q2、MCD12Q1、SoilGrids 和 NASADEM 的字段、单位、缺测／QC、公式及测试；
- 四层研究时期不变：总体事件库 2000—2023、LAI 完整年 2003—2023、五年 LAI 暴露 2008—2023、LAI／NDVI 共同样本 2008—2023；
- LAI 暴露严格使用事件年前五个完整年，主分析 5／5 年有效；4／5 年、3／10 年窗只作敏感性；
- 本附录不授权修改 SMP、恢复、F_R／F_Z、LAI／深层水模型或统计推断的科学定义。

### 16.2 规则固定但实文件待验收

| 产品／输入 | 当前可冻结内容 | 正式生产前仍需验收 | 未验收时允许做什么 |
|---|---|---|---|
| ERA5-Land | 字段、单位、层厚、日界、符号和聚合公式 | 连续至少 3 天小时文件、D+1 00 UTC、`expver`、缺测和符号 | 合成单元测试；不生成正式物理量 |
| GLDAS-2.1 | 字段、后缀语义、3 小时区间、层求和 | 实文件 `_FillValue`／`missing_value`、时间戳和坐标 | 合成单元测试；不生成正式 GLDAS 事件 |
| MCD15A3H | SDS、比例、填充类别、QC 位段和 4 天权重 | HDF4 的 SDS 维、整型、日期、QA 实值 | QC 合成测试；不生成正式 LAI 暴露 |
| MOD13Q1 | SDS、比例、可靠性、VI Quality 和合成语义 | HDF4 的日期、合成日、QC 实值和坐标 | 不生成正式 NDVI 结果 |
| MCD12Q2 | 日期、QA、多周期和回退规则 | cycle 维、绝对日期、官方 QA 示例和跨年实值 | 不生成正式动态物候窗 |
| MCD12Q1 | `LC_Type1`、`QC`、`LW` 和面积比例 | HDF4 字段、年度有效覆盖和类别实值 | 不生成正式地类掩膜 |
| NASADEM | HGT／NUM 类型、垂直基准和坡度算法 | HGT 瓦片尺寸、大端序、NUM 实值和相邻瓦片 | 平面合成测试；不生成正式地形协变量 |
| CHIRPS | 字段、单位和日／候规则；镜像样例已为 F | 正式批量文件完整性、最终版／初步版状态和哈希 | 可用已验样例做读取测试，不宣称全期验收 |
| SoilGrids | 层、单位、厚度、NoData 和聚合；样例已为 F | 所有 sand／clay 层的版本、覆盖 ID、哈希和空间完整性 | 可用样例测试，不宣称全区批量验收 |

### 16.3 暂时锁定与条件性放行

| 项目 | 放行条件 | 未放行处置 | 变更影响范围 |
|---|---|---|---|
| 研究区矢量 | 来源、版本、许可、几何、CRS、哈希和 inclusion rule 全部验收 | 不生成正式区域结果 | 空间支撑及全部下游区域结论 |
| 站点清单与使用权 | 站点、层深、时制、日界、单位、QC、权限和融合状态验收 | 主链继续；站点结论降级或跳过 | M9 站点分轨，不改主事件库 |
| 可选 ERA5 环流 | 字段、压力层、单位、小时完整性、IVT 来源和版本验收 | 删除可选诊断 | 仅 M9 环流合成 |
| SoilGrids 滚动版本 | 每次生产固定下载日期、URL、覆盖 ID 和哈希 | 不用“最新版”覆盖旧版本 | 静态协变量及使用它的模型 |
| QC／覆盖敏感性 | 在 `params.yaml` 独立登记方案名和参数 | 不覆盖主结果 | 按依赖重跑并进入规范矩阵 |

### 16.4 变更触发器

出现以下任一情况必须新建 `run_id`，保留旧结果并写偏离日志：

- 产品 collection、原生字段语义、单位、比例因子、缺测码或 QC 位定义改变；
- 时间戳／累计区间解释改变，或发现日界、时区、蒸发符号错误；
- 研究区、目标网格、面积算法、QC 主掩膜或空间／时间覆盖阈值改变；
- 动态物候回退、LAI 年合成或五年有效年规则改变；
- 原生文件哈希变化且不能证明只是无损打包差异。

仅修复不触及上述语义的代码性能问题，也须通过同一测试矩阵证明输出逐值一致后才能复用旧冻结表。任何改变样本或结局的修正都不得写成“无关紧要的预处理调整”。


## 17. 官方证据与高水平文献的采用边界

### 17.1 官方产品文档是代码级预处理的首要依据

高水平论文可以支持“为什么选这个变量、这个尺度是否合理”，但原生字段、缺测码和 QC 位段必须以对应 collection 的官方文档和实文件为准。论文中的处理若与官方指南冲突，不能覆盖官方定义。

| 产品 | 本次使用的官方依据 | 官方入口／文档 | 数据集 DOI |
|---|---|---|---|
| ERA5-Land | CDS 字段表、ERA5-Land 数据文档、累计量与符号说明 | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land | https://doi.org/10.24381/cds.e2161bac |
| GLDAS-2.1 Noah | GES DISC 产品目录、GLDAS-2 README 的变量和后缀表 | https://hydro1.gesdisc.eosdis.nasa.gov/data/GLDAS/GLDAS_NOAH025_3H.2.1/doc/README_GLDAS2.pdf | https://doi.org/10.5067/E7TYRXPJKWOQ |
| CHIRPS v2.0 | UCSB CHC 产品说明、本次归档的 v2.0 README、实文件元数据 | https://www.chc.ucsb.edu/data/chirps | 数据论文见下表 |
| MCD15A3H.061 | LP DAAC C6.1 产品页、MOD15 V6.1 用户指南 | https://lpdaac.usgs.gov/products/mcd15a3hv061/ | https://doi.org/10.5067/MODIS/MCD15A3H.061 |
| MOD13Q1.061 | LP DAAC C6.1 产品页、MOD13 V6.1 用户指南 | https://lpdaac.usgs.gov/products/mod13q1v061/；https://lpdaac.usgs.gov/documents/621/MOD13_User_Guide_V61.pdf | https://doi.org/10.5067/MODIS/MOD13Q1.061 |
| MCD12Q2.061 | LP DAAC C6.1 产品页、MCD12Q2 V6.1 用户指南 | https://lpdaac.usgs.gov/products/mcd12q2v061/；https://lpdaac.usgs.gov/documents/1417/MCD12Q2_User_Guide_V61.pdf | https://doi.org/10.5067/MODIS/MCD12Q2.061 |
| MCD12Q1.061 | LP DAAC C6.1 产品页、MCD12 V6.1 用户指南 | https://lpdaac.usgs.gov/products/mcd12q1v061/；https://lpdaac.usgs.gov/documents/1409/MCD12_User_Guide_V61.pdf | https://doi.org/10.5067/MODIS/MCD12Q1.061 |
| SoilGrids250m | ISRIC 产品文档、WCS 输出与原生 VRT 元数据 | https://www.isric.org/explore/soilgrids | 数据方法论文见下表 |
| NASADEM_HGT.001 | LP DAAC 产品页、NASADEM V1.3 用户指南 | https://lpdaac.usgs.gov/products/nasadem_hgtv001/ | https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001 |
| ERA5 可选环流 | CDS 单层／压力层字段表与实文件元数据 | https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels；https://cds.climate.copernicus.eu/datasets/reanalysis-era5-pressure-levels | https://doi.org/10.24381/cds.adbb2d47；https://doi.org/10.24381/cds.bd0915c6 |

官方网页会更新，正式生产仍须保存当次 PDF／元数据文件、访问日期和哈希，不能只保存一个可能变化的网页地址。

### 17.2 数据产品与预处理方法文献

以下每条均附 DOI；它们支持产品语义、算法背景或统计处理，不被用来替代实文件验收。

| 文献 | 本附录采用的内容 | 不据此推断的内容 | DOI |
|---|---|---|---|
| Muñoz-Sabater et al.（2021），ERA5-Land 数据论文 | 产品时空结构、陆面变量和再分析边界 | 不证明 ERA5-Land 是黄土高原站点真值 | https://doi.org/10.5194/essd-13-4349-2021 |
| Rodell et al.（2004），GLDAS 方法论文 | 陆面同化／建模系统和多变量物理背景 | 不证明所有 GLDAS 版本字段和时间后缀完全相同 | https://doi.org/10.1175/BAMS-85-3-381 |
| Funk et al.（2015），CHIRPS 数据论文 | 卫星—站点融合、产品格式和降水监测用途 | 不据此称 CHIRPS 与融合站点相互独立 | https://doi.org/10.1038/sdata.2015.66 |
| Myneni et al.（2002），MODIS LAI／FPAR 算法背景 | LAI 的冠层结构含义和反演产品背景 | 不把质量较低的反演值当作无缺测连续观测 | https://doi.org/10.1016/S0034-4257(02)00074-3 |
| Huete et al.（2002），MODIS 植被指数方法 | NDVI 的辐射与生物物理含义、合成产品背景 | 不把 NDVI 当成 LAI 或生理恢复真值 | https://doi.org/10.1016/S0034-4257(02)00096-2 |
| Gray、Sulla-Menashe & Friedl（2022），MCD12Q2 C6.1 官方用户指南 | 年物候指标、多周期、日期和 QA 的直接算法依据 | 不把产品内跨年处理等同于本项目可用后值回填暴露；指南不是期刊论文 | 官方指南无独立论文 DOI；数据集 DOI：https://doi.org/10.5067/MODIS/MCD12Q2.061 |
| Sulla-Menashe et al.（2019），MCD12 C6 地类算法 | 年土地覆盖分类、稳定化与不确定性背景 | 不把逐年标签跳变直接解释为真实土地覆盖变化 | https://doi.org/10.1016/j.rse.2018.12.013 |
| Hengl et al.（2017），SoilGrids250m | 数字土壤制图、250 m 静态土壤属性背景 | 不把预测土壤图当作逐格点实测剖面 | https://doi.org/10.1371/journal.pone.0169748 |
| Poggio et al.（2021），SoilGrids 2.0 | 更新产品及空间不确定性表达 | 不将单一均值图层解释为无不确定性真值 | https://doi.org/10.5194/soil-7-217-2021 |
| Sen（1968） | 五年 LAI 趋势的稳健斜率 | 不把短窗斜率自动解释为持续人为绿化因果 | https://doi.org/10.2307/2285891 |
| Hamed & Rao（1998） | 区域趋势存在自相关时的修正依据 | 不用其替代事件级空间依赖和年份共同冲击处理 | https://doi.org/10.1016/S0022-1694(97)00125-X |
| Steegen et al.（2016） | 透明报告多组合理预处理／分析选择 | 不做任意参数笛卡尔积后只报告有利结果 | https://doi.org/10.1177/1745691616658637 |
| Simonsohn et al.（2020） | 规范曲线和定义敏感性的展示思想 | 不用规范曲线替代主估计对象和区间解释 | https://doi.org/10.1038/s41562-020-0912-z |

### 17.3 与课题科学问题直接相关的高水平研究

| 文献 | 可迁移到本课题的部分 | 时间／空间尺度与本课题的关系 | 不可照搬的边界 | DOI |
|---|---|---|---|---|
| Zheng et al.（2022） | 黄土高原骤旱快速发展和候尺度土壤水识别具有区域先例 | 区域和候尺度与本课题直接相近 | 其 CDFDI 合并、剔除和持续规则不等于本项目 40／20、5 百分位／候和总持续≥4 候 | https://doi.org/10.1029/2021WR031464 |
| Christian et al.（2021） | 以土壤水分快速下降识别骤旱的概念依据 | 全球／多尺度思想可迁移，具体样本不同 | 不把其事件清单、百分位或持续规则当作本项目唯一标准 | https://doi.org/10.1038/s41467-021-26692-z |
| Osman et al.（2021） | 不同骤旱定义会影响事件清单和结论 | 支持本项目跨定义敏感性，而非照搬其空间样本 | 不用定义敏感性替代主定义预注册 | https://doi.org/10.5194/hess-25-565-2021 |
| Mahto & Mishra（2024） | 候尺度恢复速率、恢复期极端降水与时间窗思路 | 候尺度与 SMP／P95 序列相容 | 其事件与终止条件不完全相同，不能证明 20% 终止是唯一标准 | https://doi.org/10.1088/1748-9326/ad300c |
| Parry et al.（2016） | 将终止理解为过程并区分恢复指标的思想 | 方法思想可迁移，具体干旱系统不同 | 不把任意固定日期当作所有事件的物理恢复日 | https://doi.org/10.1177/0309133316652801 |
| Lu et al.（2026） | 绿化与干旱发展／恢复可以分阶段研究 | 支持植被背景与干旱阶段连接的问题设置 | 已说明该方向并非空白；不以“NDVI 换 LAI”宣称方法首创 | https://doi.org/10.1007/s10113-026-02661-4 |
| O & Park（2024） | 植被背景和气候条件会调节生态响应 | 为事件前冠层背景提供生态学参照 | 生态响应不等同土壤水恢复，不直接证明本课题结局 | https://doi.org/10.1038/s43247-024-01247-4 |
| Qing et al.（2023） | 土壤水状态与后续干—湿转变的物理联系 | 支持深层水作为效应修饰候选 | 全球反馈分析不证明黄土高原事件级植被因果 | https://doi.org/10.1038/s43247-023-00922-2 |
| Liu et al.（2023） | 骤旱可持续或转变，不能只分析已终止事件 | 支持保留未恢复事件和固定随访 | 不把 C 自动改称“常规干旱” | https://doi.org/10.1088/1748-9326/acfccb |

这些文献与官方指南共同形成两层依据：**论文负责科学合理性和尺度匹配，官方文档负责可重复的数据处理。** 任一论文使用较宽松 QC、不同年窗或不同空间插值，都不能成为本课题静默改变冻结规则的理由。

### 17.4 对本课题匹配度的综合判断

1. **主链匹配度最高**：ERA5-Land＋CHIRPS／GLDAS 的小时／3 小时／日尺度可在原生分辨率形成候值，符合骤旱快速发展和恢复随访的时间需求。
2. **LAI 暴露匹配度高但时间起点受限**：MCD15A3H 的 4 天观测优于 16 天 NDVI 对活跃窗的刻画，但 2002 年非完整年，五年暴露只能从 2008 年事件起完整进入主模型。
3. **动态物候比固定 4—9 月更贴合黄土高原多类型植被**：但必须接受 QC、回退和多周期审计，不能把动态窗变成按结果选择样本的工具。
4. **静态土壤与地形只作控制**：SoilGrids 和 NASADEM 的高分辨率有助于刻画空间背景，却不提供事件级因果识别。
5. **可选环流和站点是验证／解释增强项**：缺失时削弱机制表述或验证强度，不应阻塞路线一最小闭环。
6. **跨产品一致是稳健性证据，不是独立真值证明**：同源强迫、融合站点、均值回归和共同气候历史仍需保留在限制中。

## 18. 生产前最终验收清单

### 18.1 文件与字段

- [ ] 每个文件有官方 URL、实际请求、下载时间、版本、大小和 SHA256；原始文件只读。
- [ ] `source_variable_map.csv` 已使用 `sub_surface_runoff`、`precip`、`QC` 等实际字段，不再使用语义别名充当下载名。
- [ ] GLDAS 所有主链字段的 `_inst／_tavg／_acc／_f` 语义、时间戳和实际缺测属性已验收。
- [ ] MODIS 原生 HDF4 的 SDS 名、数据类型、比例、填充值和 QC 位段已由实文件复核。
- [ ] CHIRPS v2.0 final 与 preliminary、v2.0 与 v3 未静默混用。

### 18.2 时间、单位与空间

- [ ] 73 候平年／闰年测试通过，第 73 候和跨年恢复窗无日期丢失。
- [ ] ERA5-Land 日 D 使用 D+1 00 UTC 累计量，D00 不重复计入；所有累计／速率只转换一次。
- [ ] 蒸发符号、m→mm、K→°C、g/kg→%、LAI／NDVI 比例因子均通过幂等性检查。
- [ ] 状态量与通量采用不同完整性规则；缺测不被改为 0，未知窗口不归阴性。
- [ ] 面积权重来自真实交叠面积；类别只保存面积比例；GLDAS 原生 0.25°复算独立保留。
- [ ] 主空间覆盖 0.70，0.50／0.85 为独立敏感性；所有低覆盖输出为空并写原因。

### 18.3 植被、物候与暴露

- [ ] MCD15A3H 249—255 全部排除，主 QC 与 Best-only 敏感性分版。
- [ ] MOD13Q1 16 天值未被复制成独立日观测；NDVI 未冒充 LAI 真值。
- [ ] MCD12Q2 绝对日期、跨年、多周期并集、回退和有效年份<5 规则通过测试。
- [ ] 年时间／空间覆盖均≥0.70；LAI 五年窗严格为 y−5…y−1，主分析 5／5 年有效。
- [ ] 总体事件库、LAI 完整年、五年 LAI 和 LAI／NDVI 共同样本四层时期没有混写。
- [ ] 同一 `grid_id×year` 多事件共享暴露的簇审计保留；预处理没有制造伪独立暴露。

### 18.4 证据、科学边界与复核

- [ ] D／F／P 状态与实文件验收一致，需要权限的产品未冒称已下载。
- [ ] CHIRPS 样例标为 NOAA 官方镜像；SoilGrids WCS 样例标为重投影输出，原生投影证据来自 VRT。
- [ ] 研究区、站点和可选环流未放行时保持暂时锁定／条件性跳过，不生成虚假正式结论。
- [ ] 所有单元测试有输入、期望、实测、容差和代码／参数哈希；`skip` 未冒充 `pass`。
- [ ] 本附录未改变 SMP、恢复、P-term、F_R／F_Z、LAI、深层水、三出口和统计模型定义。
- [ ] R6 能从冻结原生样例独立复算至少一个日值、一个候值、一个空间聚合值和一个 QC 解码值。
- [ ] 文献均附 DOI，官方文档均保留入口；论文依据与产品字段证据没有混为一谈。

**最终放行判据**：科学参数、工程参数、原生文件、变量映射和代码哈希能够共同重建同一输出；所有 P 项在生产前完成实文件验收；任何未通过项都有停止、降级或退出记录，而不是静默插值、删样或改写结论。
