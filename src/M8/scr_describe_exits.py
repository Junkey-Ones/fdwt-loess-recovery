"""脚本名：scr_describe_exits.py（M8 · 路线二描述）
功能简介：审计出口样本并估计离散竞争风险累计发生率。
作者：Codex
版本：v0.1.0
读取数据：M8 事件级出口、事件—候随访和 M2 空间块。
生成数据：路线二样本审计和非参数累计发生率表。
其他文件：统一入口写入回执和日志。
运行示例：python -m workflow.run_module M8 --run-alias 2026-11-11_主分析
退出码：由统一入口定义。
"""
from collections import Counter, defaultdict


def sample_audit(events, exits, blocks, settings):
    """汇总出口、删失原因、空间支撑和 B 事件集中度。"""
    grid_by_episode = {event["episode_id"]: event["grid_id"] for event in events}
    by_outcome = defaultdict(Counter)
    for row in exits:
        label = row["exit_type"] or row["censor_reason"]
        block = blocks.get(grid_by_episode[row["episode_id"]])
        by_outcome[label][block] += 1
    labels = ("A", "B", "C", "missing_smp", "data_end", "unknown_fr")
    audit = [dict(outcome=label, n_event=sum(by_outcome[label].values()),
                  n_blocks=len(by_outcome[label].keys() - {None}),
                  n_without_block=by_outcome[label][None]) for label in labels]
    totals = {row["outcome"]: row["n_event"] for row in audit}
    n_blocks = len(set().union(*(by_outcome[label] for label in ("A", "B", "C"))) - {None})
    b_blocks = by_outcome["B"]
    share = max(b_blocks.values()) / totals["B"] if totals["B"] and not b_blocks[None] else None
    reasons = []
    if len(exits) < settings["multi_n"]:
        reasons.append("总事件数低于多变量门槛")
    if min(totals[label] for label in ("A", "B", "C")) < settings["multi_min_per_exit"]:
        reasons.append("至少一个出口的事件数低于多变量门槛")
    if n_blocks < settings["multi_min_blocks"]:
        reasons.append("空间块数低于多变量门槛")
    return audit, dict(n_events=len(exits), n_blocks=n_blocks, max_b_share_per_block=share,
                       multivariable_count_gate_met=not reasons, multivariable_count_gate_reasons=reasons,
                       b_share_gate_met=share is not None and share <= settings["max_b_share_per_block"])


def cumulative_incidence(person, horizon, *, strict=False):
    """估计 A、B 的累计发生率及未离场生存率。"""
    counts = defaultdict(Counter)
    for row in person:
        step = row["followup_pentad"]
        count = counts[step]
        count["censored"] += bool(row["censored"])
        if row["at_risk"]:
            count["risk"] += 1
            reclassify = strict and row["exit_B"] and row["F_R_subtype"] == "post"
            count["A"] += row["exit_A"] or reclassify
            count["B"] += row["exit_B"] and not reclassify
    survival, cif_a, cif_b = 1.0, 0.0, 0.0
    output = []
    for step in range(1, horizon + 1):
        count = counts[step]
        risk, a, b = (count[key] for key in ("risk", "A", "B"))
        if a + b > risk:
            raise ValueError("路线二出口数超过该候风险集。")
        if risk:
            cif_a += survival * a / risk
            cif_b += survival * b / risk
            survival *= 1 - (a + b) / risk
        available = risk > 0 or survival == 0
        output.append(dict(followup_pentad=step, n_at_risk=risk, n_exit_a=a, n_exit_b=b,
                           n_censored=count["censored"], cif_a=cif_a if available else None,
                           cif_b=cif_b if available else None, survival=survival if available else None,
                           probability_c=survival if available and step == horizon else None))
    return output
