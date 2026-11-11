"""脚本名：scr_audit_handoffs.py（M10 · 冻结交接核对）
功能简介：独立核对路线一冻结表的字段及关键样本总数。
作者：Codex
版本：v0.1.0
读取数据：上游 Parquet 表及字段登记。
生成数据：交接表字段、总数及通过状态。
其他文件：统一入口写入回执和日志。
运行示例：python -m workflow.run_module M10 --run-alias 2026-11-11_主分析
退出码：由统一入口定义。
"""
from collections import Counter
import csv
from io import StringIO

import pyarrow.compute as pc
import pyarrow.parquet as pq


def review_handoffs(tables, definitions):
    """核对路线一的字段顺序、入库事件与派生表的总数。"""
    aliases = {"grid_day_era5land": "grid_day", "grid_pentad_base_era5land": "grid_pentad_base",
               "event_master_base": "event_master"}
    validation = {}
    for name, path in sorted(tables.items()):
        if name.startswith("route2_"):
            continue
        parquet = pq.ParquetFile(path)
        expected = definitions[aliases.get(name, name)]["columns"]
        actual = parquet.schema_arrow.names
        validation[name] = dict(passed=expected == actual, expected=expected, actual=actual,
                                n_rows=parquet.metadata.num_rows)

    def column(name, field):
        return pq.read_table(tables[name], columns=[field]).column(field)

    def count(name):
        return validation[name]["n_rows"]

    def ids(name):
        return set(column(name, "episode_id").to_pylist())

    accepted = pc.sum(pc.cast(column("event_candidate_audit", "eligible_main"), "int64")).as_py() or 0
    master_ids = ids("event_master")
    base_ids = ids("event_master_base")
    exposure_ids = ids("event_exposure")
    annual_count = pc.sum(column("q1_annual", "n_event")).as_py() or 0
    condition_a = pc.sum(pc.cast(column("event_master", "route1_A_eligible"), "int64")).as_py() or 0
    branches = Counter(column("event_branch", "branch").to_pylist())
    checks = (
        ("候选入库", accepted, count("event_master_base"), True),
        ("事件主表", count("event_master_base"), count("event_master"), base_ids == master_ids),
        ("暴露交接", count("event_master"), count("event_exposure"), master_ids == exposure_ids),
        ("Q1 年度事件数", condition_a, annual_count, True),
        ("R 分支", pc.sum(pc.cast(column("event_master", "F_R"), "int64")).as_py() or 0, branches["F_R"], True),
        ("Z 分支", pc.sum(pc.cast(column("event_master", "F_Z"), "int64")).as_py() or 0, branches["F_Z"], True),
    )
    totals = [dict(check=key, n_expected=expected, n_actual=actual, passed=expected == actual and keys_match)
              for key, expected, actual, keys_match in checks]
    return totals, validation


def review_deviations(content, columns):
    """核对冻结偏离登记的字段、键及结果查看分类。"""
    source = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    if source.fieldnames != columns:
        raise ValueError("冻结偏离登记表头与字段登记不符。")
    rows = list(source)
    keys = [row["deviation_id"] for row in rows]
    if not all(keys) or len(set(keys)) != len(keys):
        raise ValueError("冻结偏离登记缺少标识或包含重复项。")
    output = []
    for row in rows:
        seen = row["outcome_seen"]
        classification = row["preregistered_or_posthoc"]
        consistent = (seen, classification) in {
            ("no", "pre_outcome_deviation"), ("unknown", "classification_pending"),
        } or (seen == "yes" and classification.startswith("posthoc"))
        output.append({**row, "review_status": "classification_pending" if consistent and seen == "unknown"
                       else "passed" if consistent else "requires_review"})
    return output


def summarize_missing(events):
    """分别盘点事件删失及适用窗口内未知的降水结局。"""
    censored = Counter(row["censor_type"] or "unknown_censor_type" for row in events if row["right_censored"])
    recovered = [row for row in events if row["t_e"] is not None]
    summary = [dict(category="右删失", reason=reason, n_event=n, denominator=len(events))
               for reason, n in sorted(censored.items())]
    for field in ("P_term", "F_R", "F_Z"):
        summary.append(dict(category="恢复后结局未知", reason=field,
                            n_event=sum(row[field] is None for row in recovered), denominator=len(recovered)))
    return summary
