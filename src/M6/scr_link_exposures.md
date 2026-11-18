# scr_link_exposures

非空植被年表若完全不包含当前配置的掩膜及QC版本，立即报错；不能把传入旧年表解释为科学性的全缺测。

连接事件前植被、土壤水和协变量。输入 M3/M5 及年度植被表。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M6。
日志、路径和退出码由统一入口管理。

模块由统一入口调度，读取同别名的已验证交接。详见下游编排说明。

面板 `main` 使用 `lai.main_requires_full`（5/5）；`lai_four_of_five` 使用 `sensitivity.lai.relaxed_valid_years`（4/5）。两者都取事件前五个完整日历年，覆盖门槛和QC相同。五年有效时全部使用；仅四年有效时使用四年均值及真实年份间隔的Sen斜率，不填补缺年，不使用事件当年。

`LAI_full_window` 始终表示五年全有效；`LAI_window_eligible` 表示通过当前方案门槛，模型L/I及暴露簇按后者筛选。新增 `LAI_required_valid_years`、`LAI_valid_years`（JSON实际年份列表）、`LAI_valid_year_span`（末年减首年）用于审计。NDVI仍保留原5/5规则。4/5现为Q3修订主分析，增加样本不能保证拟合或bootstrap成功，也不消除缺测选择偏倚。

主分析按 `lai.mask_version` 和 `lai.qc_version` 选择植被年值。入选记录须通过年度有效标记和时间、空间覆盖门槛。静态协变量和事件前土壤水中的非有限数值按缺失处理。原生 MODIS 年合成已由 `scr_prepare_vegetation` 接入。2026-11-15 起配置采用 `aerosol_allowed`，连接时必须匹配该版本，旧 `main` 年表不能替代新规则年表。
LAI_in_exposure_period 单独记录事件年资格。LAI_n_valid_years 是原始有效年数，LAI_window_eligible 同时要求事件年和当前方案年数门槛。
