# M10 论文图件

通过 `python -m workflow.run_module M10 --run-alias <已冻结别名>` 调用。M10 复核通过后从冻结结果生成图件，将文件及哈希写入模块回执，再发布到 `outputs/{run_alias}/figures`。图件清单包含图注、源表、行数、产品、时期、规范和缺项原因。

排版参考 [Nature 图稿指南](https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/)。单栏 89 mm，双栏 183 mm，常规文字 6–7 pt，英文无衬线字体，面板用小写字母。PDF 保留嵌入字体，SVG 保留文本，PNG 为 600 dpi 预览。投稿时可按目标期刊的具体规格调整。

| 图件 | 冻结来源及含义 |
| --- | --- |
| Fig. 1 | 样本流逐步保留、排除和实际分母 |
| Fig. 2 | 条件 A 的恢复时间、幅度与速率经验累积分布，虚线为中位数 |
| Fig. 3 | 条件 A 的降水接续类别计数和阳性滞后分布，未知窗口单列 |
| Fig. 5 | 同支撑的双向事件匹配率及 Jaccard 指数 |

现有 Fig. 5 表示事件清单一致性。Fig. 4、6、7 在清单中标记待发布，分别依赖尚未接入的 Q3 边际估计、规范复算和路线二路径估计。缺少有效观测时记录原因。正式图件随冻结身份发布，已有别名的图件发生变化时需重新冻结。
