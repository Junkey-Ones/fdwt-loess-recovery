# 聚类得分工具

空间×年份协方差使用三项组合及各项G/(G-1)修正，见[sandwich官方说明](https://sandwich.r-forge.r-project.org/reference/vcovCL.html)。实质非正半定时返回不可用并报告最小特征值，不隐式修正后宣称精确推断。

年份敏感性为中心化年份簇得分的Rademacher乘子及信息矩阵逆的一次线性化系数扰动。参考[Kline与Santos得分bootstrap](https://www.nber.org/papers/w16127)。此处实现是未受限、非学生化的渐近敏感性区间，不是原文所有检验变体或严格原假设下的有限样本精确检验，不替换主Holm检验。不将“已实现”写成“少簇覆盖率已校准”。参数读取infer.year_score_bootstrap；主概率预测应对每次系数扰动重新作非线性变换。

调用方提供完整历史对应的年份/空间标签，不得逐候随机分簇。输入/输出留在内存，经统一M7发布诊断和结果。
