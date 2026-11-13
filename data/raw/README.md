# 原始数据目录与来源

**2026-11-13 盘点**。本地共 **27,393 个文件，348.28 GiB**。统计排除本 README，包含 ZIP、已解压副本和 1 份 GLEAM 下载辅助文本。点表格第一列可打开本地目录，最后一列是产品发布或下载入口。具体下载日期、请求编号和许可按批次登记。

当前主分析期为 **2003–2023 年**，研究区为 **102–115°E、34–41°N**。目录表记录本地覆盖，变量和网格来自代表文件或产品文档。 [研究区登记](../../metadata/study_area_manifest.csv)

## 文件夹结构

```text
data/raw/
├── era5_land/
│   ├── instant/
│   ├── accumulated/
│   ├── runoff_components/
│   └── surface_runoff/
├── era5_single_levels/
│   ├── accumulated/
│   ├── instant/
│   ├── sm/
│   └── wind/
├── esa_cci_sm/passive/v09.2/
├── gleam/
│   ├── Et/v4.3a/
│   ├── SMrz/v4.3a/
│   ├── SMs/v4.3a/
│   └── gleam_download_script.txt
├── gosif/v2/
├── modis/
│   ├── MCD12Q1/
│   │   ├── V061/
│   │   └── legacy_samples/V061/
│   ├── MCD12Q2/V061/
│   ├── MCD15A2H/V061/
│   └── MCD15A3H/V061/<年份>/
├── soilgrids/v2.0/
├── nasadem/HGT.001/
├── aridity/global_ai_pet_v3/Global-AI_ET0__annual_v3_1/
├── irrigation/gmia/v5/
└── README.md
```

## 主分析入库清单

| 本地目录 | 文件数 | GiB | 本地覆盖 | 时间与空间尺度、格式 | 字段与用途 | 官方来源 |
|---|---:|---:|---|---|---|---|
| [`era5_land/instant`](./era5_land/instant/) | 277 | 28.700 | 2001-01 至 2023-12，另有 2024-01-01 | 小时，0.1°，NetCDF4 | swvl1–swvl4（m³/m³）、t2m（K），样本另有 d2m、u10、v10 | [Copernicus CDS](https://doi.org/10.24381/cds.e2161bac) |
| [`era5_land/accumulated`](./era5_land/accumulated/) | 277 | 19.110 | 2001-01 至 2023-12，另有 2024-01-01 | 小时，0.1°，NetCDF4 | tp、e、pev（m 水当量），样本另有 ssrd（J/m²）。末日补档含 sro、ssro | [Copernicus CDS](https://doi.org/10.24381/cds.e2161bac) |
| [`era5_land/runoff_components`](./era5_land/runoff_components/) | 288 | 5.507 | 2000-01 至 2023-12 | 小时，0.1°，NetCDF4 | sro、ssro（m），水量平衡 | [Copernicus CDS](https://doi.org/10.24381/cds.e2161bac) |
| [`era5_land/surface_runoff`](./era5_land/surface_runoff/) | 276 | 1.802 | 2001-01 至 2023-12 | 小时，0.1°，NetCDF4 | sro（m），重叠批次核对 | [Copernicus CDS](https://doi.org/10.24381/cds.e2161bac) |
| [`modis/MCD12Q1/V061`](./modis/MCD12Q1/V061/) | 115 | 1.115 | 2001–2023，每年 5 块 | 年度，500 m，HDF4 | LC_Type1、QC、LW，植被掩膜和地类协变量 | [NASA Earthdata](https://doi.org/10.5067/MODIS/MCD12Q1.061) |
| [`modis/MCD12Q2/V061`](./modis/MCD12Q2/V061/) | 105 | 28.173 | 2003–2023，每年 5 块 | 年度，500 m，HDF4 | Greenup、Dormancy、NumCycles、EVI_Amplitude、QA_Overall、QA_Detailed，动态物候窗 | [NASA Earthdata](https://doi.org/10.5067/MODIS/MCD12Q2.061) |
| [`modis/MCD15A3H/V061`](./modis/MCD15A3H/V061/) | 9,615 | 72.640 | 2003–2023，按年归档，45 个组合在已提供的 CMR 查询中无记录 | 4 日，500 m，HDF4 | Lai_500m、FparLai_QC、FparExtra_QC，事件前五年植被暴露 | [NASA Earthdata](https://doi.org/10.5067/MODIS/MCD15A3H.061) |
| [`soilgrids/v2.0`](./soilgrids/v2.0/) | 6 | 0.105 | 静态，覆盖研究区 | 约 250 m，GeoTIFF | sand 和 clay 各有 0–5、5–15、15–30 cm 的 mean，原生单位 g/kg | [ISRIC SoilGrids](https://isric.org/explore/soilgrids) |
| [`nasadem/HGT.001`](./nasadem/HGT.001/) | 91 | 1.000 | 静态，91 块核心瓦片 | 1″，1° 瓦片，ZIP | 每瓦片 HGT、NUM 各 3601×3601，用于高程和派生坡度 | [NASA Earthdata](https://doi.org/10.5067/MEaSUREs/NASADEM/NASADEM_HGT.001) |

## 辅助与背景数据

| 本地目录 | 文件数 | GiB | 本地覆盖 | 时间与空间尺度、格式 | 字段与用途 | 官方来源 |
|---|---:|---:|---|---|---|---|
| [`era5_single_levels/accumulated`](./era5_single_levels/accumulated/) | 276 | 1.830 | 2001-01 至 2023-12 | 小时，0.25°，NetCDF4 | tp、e、pev、ssrd，备用气象 | [Copernicus CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) |
| [`era5_single_levels/instant`](./era5_single_levels/instant/) | 276 | 1.138 | 2001-01 至 2023-12 | 小时，0.25°，NetCDF4 | t2m、d2m（K） | [Copernicus CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) |
| [`era5_single_levels/sm`](./era5_single_levels/sm/) | 216 | 1.163 | 2006-01 至 2023-12 | 小时，0.25°，NetCDF4 | swvl1–swvl3（m³/m³） | [Copernicus CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) |
| [`era5_single_levels/wind`](./era5_single_levels/wind/) | 276 | 1.581 | 2001-01 至 2023-12 | 小时，0.25°，NetCDF4 | u10、v10（m/s） | [Copernicus CDS](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels) |
| [`esa_cci_sm/passive/v09.2`](./esa_cci_sm/passive/v09.2/) | 8,766 | 14.110 | 2001-01-01 至 2024-12-31 | 逐日，全球 0.25°，NetCDF4 | 被动微波表层体积土壤水（m³/m³），表层响应对照 | [ESA CCI v09.2](https://climate.esa.int/en/catalogue/c93c99588d5848b1ac7833e3bc6d5c2d/) |
| [`gleam/Et/v4.3a`](./gleam/Et/v4.3a/) | 26 | 30.774 | 2000–2025，每年一份 | 逐日，0.1°，NetCDF4 | Et 蒸腾（mm/day） | [GLEAM 下载](https://www.gleam.eu/#downloads) |
| [`gleam/SMrz/v4.3a`](./gleam/SMrz/v4.3a/) | 26 | 43.074 | 2000–2025，每年一份 | 逐日，0.1°，NetCDF4 | SMrz 根区土壤水（m³/m³） | [GLEAM 下载](https://www.gleam.eu/#downloads) |
| [`gleam/SMs/v4.3a`](./gleam/SMs/v4.3a/) | 26 | 43.383 | 2000–2025，每年一份 | 逐日，0.1°，NetCDF4 | SMs 表层土壤水（m³/m³） | [GLEAM 下载](https://www.gleam.eu/#downloads) |
| [`gosif/v2`](./gosif/v2/) | 1,143 | 9.385 | 2000-057 至 2024-361，缺 2000 年前 7 期 | 8 日，全球 0.05°，TIFF.GZ | 太阳诱导叶绿素荧光，比例因子 0.0001 | [UNH GOSIF 发布页](https://globalecology.unh.edu/data/GOSIF.html) |
| [`modis/MCD15A2H/V061`](./modis/MCD15A2H/V061/) | 5,302 | 42.648 | 2002-185 至 2025-361，瓦片覆盖有差异 | 8 日，500 m，HDF4 | LAI、FPAR、标准差和两层 QA，用于读取测试和辅助诊断 | [NASA Earthdata](https://doi.org/10.5067/MODIS/MCD15A2H.061) |
| [`modis/MCD12Q1/legacy_samples/V061`](./modis/MCD12Q1/legacy_samples/V061/) | 6 | 0.055 | 2003、2022 各 3 块 | 年度，500 m，HDF4 | 早期地类样例 | [NASA Earthdata](https://doi.org/10.5067/MODIS/MCD12Q1.061) |
| [`aridity/global_ai_pet_v3/Global-AI_ET0__annual_v3_1`](./aridity/global_ai_pet_v3/Global-AI_ET0__annual_v3_1/) | 2 | 0.979 | 1970–2000 气候态 | 30″，GeoTIFF 与 ZIP | AI 独立栅格及含 AI、ET₀ 和说明的归档，干湿背景 | [作者数据发布页](https://doi.org/10.6084/m9.figshare.7504448) |
| [`irrigation/gmia/v5`](./irrigation/gmia/v5/) | 1 | 0.002 | 约 2005 年 | 全球 5′，ASCII 栅格 ZIP | 具备灌溉设施的面积占格点面积百分比 | [FAO AQUASTAT](https://www.fao.org/aquastat/zh/geospatial-information/global-maps-irrigated-areas/latest-version/) |

## 主分析数据的读取要点

- **ERA5-Land**。抽查网格为 100–115°E、33–42°N。四层土壤水分别对应 0–7、7–28、28–100、100–289 cm。前三层构成根区，第四层用于深层水。两份 2024-01-01 补档均为 UTC 00:00–23:00。累计通量需核验 00 UTC 归属、蒸发符号和跨月边界。当前主分析无需补 2000 年的瞬时场与累计场。 [ECMWF 产品文档](https://confluence.ecmwf.int/spaces/CKB/pages/140385202/ERA5-Land+data+documentation)
- **MODIS**。研究区涉及 `h25v04`、`h25v05`、`h26v04`、`h26v05`、`h27v05`。文件名中的 `AYYYYDDD` 为年与年积日。四日 LAI 的原始值按 0.1 缩放，先识别填充值和 QA，再做合成。八日 LAI 的各瓦片覆盖差异详见历史盘点。 [NASA 瓦片网格](https://modis-land.gsfc.nasa.gov/MODLAND_grid.html) · [历史盘点](../../docs/原始数据清单.md)
- **SoilGrids**。6 个 TIFF 共用约 250 m 的 Goode Homolosine 网格，覆盖研究区。区内约 2.22% 像元在六层同时为零，文件未标注 NoData，需确认零值含义后再聚合。
- **NASADEM**。瓦片名表示西南角，核心组合为 N34–N40 × E102–E114。91 份 ZIP 已通过 CRC 校验。坡度计算需保留相邻像元，并处理瓦片边缘的重叠行列。

## 待补数据

四日 LAI 共 **9,615 份**。标准四日日历有 9,660 个日期 × 瓦片组合，本地剩余的 **45 个空缺与已提供的 NASA CMR 查询结果逐项一致**。本次核对了文件名、覆盖、重复键及 HDF4 文件头，尚未解码像元或重新查询 CMR。

| 合成起始日期 | CMR 查询中无匹配的瓦片 | 组合数 |
|---|---|---:|
| 2003-12-19、2016-02-22 | 全部 5 块 | 10 |
| 2020-08-20 | h26v04 | 1 |
| 2020-08-24、08-28 | h26v04、h27v05 | 4 |
| 2022-04-03、04-07、04-11、10-12、10-16、10-20 | 全部 5 块 | 30 |

这些日期在预处理中保留缺测，按 SOP 核验活跃窗覆盖率。原始 HDF 按文件名中的年份存入 [四日 LAI 目录](./modis/MCD15A3H/V061/)。 [NASA 产品入口](https://doi.org/10.5067/MODIS/MCD15A3H.061)

稳健性分析的三组数据尚未入库。陆面产品复算使用 [GLDAS-2.1 Noah](https://doi.org/10.5067/E7TYRXPJKWOQ)，降水替换使用 [CHIRPS v2.0](https://data.chc.ucsb.edu/products/CHIRPS-2.0/)，NDVI 共同样本对照使用 [MOD13Q1.061](https://doi.org/10.5067/MODIS/MOD13Q1.061)。

## 入库和正式验收

保留下载时的原始文件名，按上表归档。原始数据目录供流水线只读，中间表写入 `data/interim`。本地盘点记录文件存在性和覆盖情况。M1 正式验收还需核验可读性、实际时空坐标、单位、累计方式、填充值、QA 和数值范围，并逐批登记来源、版本、许可、请求信息及逐文件 SHA-256。 [原始文件登记表](../../metadata/source_file_manifest.csv) · [变量映射表](../../metadata/source_variable_map.csv) · [预处理 SOP](../../docs/论文方向与构想/黄土高原FD-WT_v1.3.1_分产品原生变量与预处理SOP附录.md)
