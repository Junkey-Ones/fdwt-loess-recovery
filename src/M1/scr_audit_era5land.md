# M1 ERA5-Land 原始数据验收

逐月读取主产品 NetCDF，核验 UTC 小时轴、网格、物理范围、比例因子、缺测和累计步长。输出文件哈希、验收记录、变量映射、年度覆盖及缺项表。其他产品在覆盖表登记为条件性跳过。

## 输入与输出

- 输入为同一别名的 M0 正式冻结、`data/raw/era5_land/` 三个正式批次及末日补档、`metadata/local/era5land_sources.yaml`。
- `runoff_components` 提供两个径流分量，末日结算使用 `accumulated` 的次年元旦补档。重叠的 `surface_runoff` 单分量批次留作核对。2003 年 1 月和 2023 年 12 月首三个日历日的实值、坐标及缺测掩膜抽查一致。
- 报告位于 `outputs/{run_alias}/reports/`。M1 回执位于 `logs/{run_alias}/module_io_M1.json`。年度日和候的逐格点有效数由 M2 判定。

## 来源登记

在 `metadata/local/era5land_sources.yaml` 为 `instant`、`accumulated`、`runoff_components`、`terminal` 分别建立以下结构。示例字段必须依据该批次的实际下载记录填写。只有确实核实对应证据时才填写受控取值。

```yaml
instant:
  collection_version: ""
  download_date: ""
  source_url: ""
  request_id: ""
  license: ""
  access_status: allowed
  reviewer: ""
  verification_date: ""
  time_zone: UTC
  timestamp_meaning: valid_time
  production_stream: consolidated
```

`accumulated`、`runoff_components`、`terminal` 还需要 `accumulation_type: forecast_step_cumulative`。`accumulated` 和 `terminal` 还需要 `evaporation_sign: upward_negative`。每批来源 URL 和请求编号至少填一项。若一批文件来自多次下载，登记应能追溯该批所有原文件的来源。

## 执行

从项目根目录启动中文向导，先单独正式冻结 M0，再以同一别名选择 M1。批量入口为 `python -m workflow.run_module M1 --run-alias 2026-11-10_主分析`。

证据缺失时仍生成审计表，状态为 `exited`，M2 入口保持关闭。补齐证据或替换文件后使用新别名，旧审计保留。
