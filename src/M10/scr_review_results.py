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


def review_window(rule, start, end):
    """将结局窗口端点转换为需要复核的候键。"""
    anchors = {"t_min": start, "t_e": end}
    limits = []
    for expression in rule:
        for name, value in anchors.items():
            if expression.startswith(name):
                limits.append(value + int(expression[len(name):] or "0"))
                break
        else:
            raise ValueError(f"复核发现未识别的结局窗口端点：{expression}")
    return range(limits[0], limits[1] + 1)


def review_precipitation(observations, window, minimum):
    """独立重算完整窗口内的阳性状态及首次阳性候。"""
    first = None
    for t in window:
        candidate = observations.get(t, {})
        rain, p95 = candidate.get("p_mm"), candidate.get("p95_mm")
        if rain is None or p95 is None or not candidate.get("p95_usable"):
            return None, None
        if first is None and rain > minimum and rain >= p95:
            first = t
    return (first is not None, first) if window else (None, None)


def review_events(events, pentads, params):
    """分层复算事件的恢复差、速率和降水接续。"""
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
    required = defaultdict(set)
    branches = (("pterm", "P_term", "Lag_P", "t_P95"), ("fr", "F_R", "Lag_FR", "t_w_R"))
    for row in sample:
        if row["t_e"] is not None:
            key = row["product"], row["grid_id"], row["support_id"]
            required[key].update(range(row["t_min"], row["t_e"] + 1))
            for rule, *_ in branches:
                required[key].update(review_window(params[rule]["window"], row["t_min"], row["t_e"]))
    lookup = defaultdict(dict)
    for row in pentads:
        key = row["product_combo"], row["grid_id"], row["support_id"]
        if row["t_abs"] in required.get(key, ()):
            lookup[key][row["t_abs"]] = row
    results = []
    for row in sample:
        start, end = row["t_min"], row["t_e"]
        issues = []
        if inconsistent_censoring(row):
            issues.append("删失状态与终止锚点不一致")
        if end is not None:
            key = (row["product"], row["grid_id"], row["support_id"])
            observations = lookup[key]
            a, b = (observations.get(t, {}).get("smp") for t in (start, end))
            if a is None or b is None or end <= start:
                issues.append("恢复锚点")
            elif (row.get("RT") != end-start or row.get("delta_SMP") is None or row.get("RR") is None
                  or not isclose(row["delta_SMP"], b-a) or not isclose(row["RR"], (b-a)/(end-start))):
                issues.append("恢复算式")
            threshold = params["recovery"]["terminate_smp"]
            if b is not None and b <= threshold:
                issues.append("终止候未超过恢复阈值")
            for t in range(start + 1, end):
                value = observations.get(t, {}).get("smp")
                if value is None or value > threshold:
                    issues.append("终止前已越过恢复阈值或随访断开")
                    break
        for rule, flag, lag, anchor in branches:
            expected_flag = expected_anchor = None
            if end is not None:
                expected_flag, expected_anchor = review_precipitation(
                    observations, review_window(params[rule]["window"], start, end), params[rule]["min_p_mm"])
            if row.get(flag) != expected_flag or row.get(anchor) != expected_anchor:
                issues.append(f"{flag} 判定或首个降水候")
            if row.get(lag) != (expected_anchor - start if expected_anchor is not None else None):
                issues.append(lag)
            if flag == "F_R":
                offset = expected_anchor - end if expected_anchor is not None else None
                subtype = None if offset is None else "pre" if offset < 0 else "sync" if offset == 0 else "post"
                if row.get("Offset_FR") != offset or row.get("F_R_subtype") != subtype:
                    issues.append("F_R 相对终止候的位置")
        results.append(dict(episode_id=row["episode_id"], passed=not issues, issues="；".join(issues)))
    return results
