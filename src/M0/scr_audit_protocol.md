# M0 协议冻结前审计

`scr_audit_protocol.py` 检查协议、配置和验收登记，并列出正式冻结的阻断项。

## 输入与输出

- 输入为研究协议目录中的五份 v1.3.1 文档、模块化说明、AI 工作包，`config/` 下的参数、Schema、规范矩阵和偏离台账，以及 `metadata/` 下的公开登记。
- 输出为标准输出中的 JSON 和 `logs/{run_alias}/M0/` 下的单次 JSONL。日志包含逐项判定和所读输入的 SHA-256。同一别名再次审计会新增日志。
- `failed` 表示审计检查失败，CLI 退出码为 2。`conditional_skipped` 表示登记条件未满足。`not_run` 表示相应实文件验收未执行。检查通过时审计状态为 `descriptive_only`，CLI 退出码为 0，正式区域放行仍为关闭。

## 运行

在项目根目录运行 `..venvScriptspython.exe -m workflow.run_module`，选择「指定模块」，输入 `M0` 并确认冻结前审计。批量入口可用 `..venvScriptspython.exe -m workflow.run_module M0 --run-alias 2026-11-10_M0审计 --progress plain`。加 `--dry-run` 只核对计划。

## 待澄清与验收

| 项目 | 当前证据和处理 |
| --- | --- |
| `event_master` | 已按工作包 §6.13 补齐 M5 主表列。暴露保留在 `event_exposure`，M6 兼容视图由两表连接生成。 |
| `event_precip` | 已补齐工作包 §6.15 声明的复合主键字段 `p_term_definition`。 |
| 随机种子 | 已登记 `268614731`，标识 `seed_m0_v1`。 |
| 规范曲线 | 已按估计对象逐项登记规格、计数和适用规则。主规格计一次，敏感性每次切换一个定义族。 |
| 研究区 | 项目负责人确认采用完整矩形 102–115°E、34–41°N。登记 ID 为 `loess_rectangle_v2`，偏离 ID 为 `dev_m0_rectangle_v2`。M0 复核源文件哈希、几何及球面面积。格点交叠面积与空间交接产物由下游生成。 |
| 其他实文件 | M1 的原始文件与变量映射、站点及环流证据均需各自验收。公开空表和文件盘点仅供识别待验项。 |
| 冻结路径 | 选择「正式冻结 M0」可在审计通过后封存 JSON、运行索引和 M0 回执。具体路径及续跑规则见[冻结入口](../../workflow/freeze_m0.md)。 |

本阶段验证配置与审计入口。SOP 科学序列和原生实文件验收随对应模块接入。统计家族配置来自预注册 §7.3，审计检查登记结构，测试核对预注册成员及阈值。
