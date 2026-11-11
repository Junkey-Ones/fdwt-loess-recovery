# scr_route1_summary

构建路线一风险集及主描述。输入 M3/M5；输出风险表、分布和比例。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M7。
日志、路径和退出码由统一入口管理。

模块由统一入口调度，读取同别名的已验证交接。详见下游编排说明。

`q1_annual` 输出条件 A 的年度中位数、RT 的四分位端点，以及 ΔSMP 和 RR 的均值。RT 四分位点采用包含端点的线性插值。年度样本量门槛沿用配置。

`trend_estimate` 输出 Sen 斜率、普通 Mann–Kendall 概率、lag-1 Ljung–Box 概率和 Hamed–Rao 敏感性。Ljung–Box 使用年度指标原序列，Hamed–Rao 使用扣除 Sen 斜率后的平均秩。显著自相关的判据为两侧 95% 正态近似界，修正因子保留自相关符号。按配置选择主检验后，RT、ΔSMP、RR 作为一个家族执行 Holm 校正。有效年份中间有断档时，保留按实际年份计算的 Sen 斜率及普通 Mann–Kendall 概率，标记 `annual_gaps`，主检验和序列自相关结果留空。年度指标恒定时，趋势概率为 1。

`trend_estimate_sensitivity` 另外记录预注册的 15 年和 20 年门槛，每套门槛独立做家族校正。

`q2_lag_result` 报告候差中位数和四分位端点。Lag_FR 与 Offset_FR 使用条件 A 中 F_R 阳性事件，Lag_P 使用 P-term 阳性事件。

公式参照 [Hamed 与 Rao](https://doi.org/10.1016/S0022-1694(97)00125-X) 及 [Ljung 与 Box](https://doi.org/10.1093/biomet/65.2.297)。
