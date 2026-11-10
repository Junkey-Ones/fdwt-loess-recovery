"""独立复核事件恢复算式和结局定义域。输入冻结 M5 事件与 M3 候表。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M10。
日志、路径和退出码由统一入口管理。
"""
from collections import defaultdict
from math import isclose
from random import Random


def inconsistent_censoring(event):
    """检查事件终止、删失锚点与条件 A 是否相容。"""
    end = event["t_e"]
    censor = event.get("censor_t_abs")
    if end is None:
        return (not event["right_censored"] or censor is None or censor < event["t_min"]
                or event["route1_A_eligible"])
    return event["right_censored"] or censor is not None


def review_events(events, pentads, params):
    """分层复算事件的恢复差、速率和降水 Lag 定义域。"""
    lookup = {(row["product_combo"], row["grid_id"], row["support_id"], row["t_abs"]): row["smp"]
              for row in pentads}
    strata = defaultdict(list)
    for event in sorted(events, key=lambda row: row["episode_id"]):
        key = (event["product"], event["year"] // 10, event["right_censored"], event.get("F_R_status"))
        strata[key].append(event)
    rng = Random(params["random"]["seed"])
    for rows in strata.values():
        rng.shuffle(rows)
    sample = []
    minimum = params["review"]["minimum_events"]
    while strata and len(sample) < minimum:
        for key in list(strata):
            sample.append(strata[key].pop())
            if not strata[key]:
                del strata[key]
    # 状态与时间定义域是全量审计，数值复算仍按分层样本执行。
    sampled_ids = {row["episode_id"] for row in sample}
    for row in events:
        if inconsistent_censoring(row):
            if row["episode_id"] not in sampled_ids:
                sample.append(row)
                sampled_ids.add(row["episode_id"])
    results = []
    for row in sample:
        start, end = row["t_min"], row["t_e"]
        issues = []
        if inconsistent_censoring(row):
            issues.append("删失状态与终止锚点不一致")
        if end is not None:
            key = (row["product"], row["grid_id"], row["support_id"])
            a, b = lookup.get((*key, start)), lookup.get((*key, end))
            if a is None or b is None or end <= start:
                issues.append("恢复锚点")
            elif (row.get("RT") != end-start or row.get("delta_SMP") is None or row.get("RR") is None
                  or not isclose(row["delta_SMP"], b-a) or not isclose(row["RR"], (b-a)/(end-start))):
                issues.append("恢复算式")
        for flag, lag, anchor in (("P_term", "Lag_P", "t_P95"), ("F_R", "Lag_FR", "t_w_R")):
            t = row.get(anchor)
            expected = t-start if row.get(flag) is True and t is not None else None
            if row.get(lag) != expected or (row.get(flag) is True and t is None):
                issues.append(lag)
        results.append(dict(episode_id=row["episode_id"], passed=not issues, issues="；".join(issues)))
    return results
