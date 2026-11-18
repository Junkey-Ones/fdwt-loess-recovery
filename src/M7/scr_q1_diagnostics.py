"""Q1删失、完整随访、季末截断及年度伴随诊断。
作者：Codex。输入：冻结风险表/事件/格点候表；输出：M7诊断表。
运行：workflow.run_module M7；不改写主风险表或上游输入。
"""
from collections import Counter, defaultdict
from math import isfinite
from statistics import mean


def censor_audit(risk, events, version, horizon, params):
    """按入组年份分列互斥末次状态；没有任何有效候者也计入分母。"""
    by_id = {r["episode_id"]: r for r in events}
    last = {}
    for row in risk:
        key = row["episode_id"]
        if key not in last or row["followup_pentad"] > last[key]["followup_pentad"]:
            last[key] = row
    groups = defaultdict(Counter)
    for key, row in last.items():
        reason = "recovered" if row["recovery_event"] else row.get("censor_reason") or "unknown"
        for year in (None, by_id[key]["year"]):
            groups[year][reason] += 1
            groups[year]["zero_followup"] += not row["at_risk"]
            groups[year]["enrolled"] += 1
    if not groups:
        groups[None] = Counter()
    output = []
    for year, counts in sorted(groups.items(), key=lambda pair: -1 if pair[0] is None else pair[0]):
        missing = counts["missing"]
        ipcw = ("not_applicable_no_missing_censoring" if missing == 0 else "insufficient_censoring_support"
                if missing < params["infer"]["min_event_per_arm"] else "requires_ipcw_model")
        output.append(dict(version=version, H=horizon, domain="all" if year is None else "year", year=year or 0,
                           **{f"n_{key}":counts[key] for key in ("enrolled","recovered","administrative","missing",
                              "data_end","season_end","phenology_missing","unknown","zero_followup")}, ipcw_status=ipcw))
    return output


def followup_subset(risk, mode):
    """完整随访按结局可判定性筛选；活跃窗截断后不允许重新进入。"""
    histories = defaultdict(list)
    for row in risk:
        histories[row["episode_id"]].append(row)
    selected = []
    for history in histories.values():
        history.sort(key=lambda r:r["followup_pentad"])
        if mode == "complete_followup":
            end = history[-1]
            if end["recovery_event"] or end.get("censor_administrative"):
                selected.extend(dict(r) for r in history)
        elif mode == "active_window":
            kept = []
            for row in history:
                if row["at_risk"] and row.get("active_flag") is not True:
                    reason = "phenology_missing" if row.get("active_flag") is None else "season_end"
                    if kept:
                        kept[-1].update(censor_reason=reason, censor_administrative=False)
                    else:
                        kept.append(dict(row, followup_pentad=0, t_abs=row["t0_tmin"], at_risk=False,
                                         recovery_event=False, censor_reason=reason, censor_administrative=False))
                    break
                kept.append(dict(row))
            selected.extend(kept)
        else:
            raise ValueError(f"未登记的随访敏感性：{mode}")
    return selected


def annual_companions(batches, masks, events, params):
    """固定植被格点域按格点年等权报告L与回退率；完整性按活跃候计数。"""
    eligible = {r["grid_id"] for r in masks if r["mask_include"]}
    states = {}
    for batch in batches:
        for row in batch.to_pylist():
            if row["grid_id"] not in eligible:
                continue
            key = row["grid_id"], row["year"]
            state = states.setdefault(key, {"L":None,"fallback":None,"active":0,"smp":0,"p":0})
            length = row.get("active_window_length_L")
            if length is not None:
                if state["L"] is not None and state["L"] != length:
                    raise ValueError("同一格点年出现不同活跃窗长度，不能混合支撑域。")
                state["L"], state["fallback"] = length, row.get("phenology_fallback")
            if row.get("active_flag") is True:
                state["active"] += 1
                for field, target in (("smp","smp"),("p_mm","p")):
                    value = row.get(field)
                    state[target] += value is not None and isfinite(value)
    counts = Counter(e["year"] for e in events if e["route1_A_eligible"])
    groups = defaultdict(list)
    for (_, year), state in states.items():
        groups[year].append(state)
    output = []
    for year in range(params["time"]["year_start"],params["time"]["year_end"]+1):
        group = groups[year]
        valid = [r for r in group if r["L"] is not None and r["L"] > 0]
        fallback = [r["fallback"] for r in valid if r["fallback"] is not None]
        active = sum(r["active"] for r in group)
        output.append(dict(year=year, n_grid_year=len(group), n_vegetation_grids=len(eligible),
                           n_valid_phenology=len(valid), n_fallback_denominator=len(fallback), n_a=counts[year],
                           mean_active_pentads=mean(r["L"] for r in valid) if valid else None,
                           phenology_fallback_rate=mean(fallback) if fallback else None,
                           n_active_pentads=active,
                           smp_completeness=sum(r["smp"] for r in group)/active if active else None,
                           precip_completeness=sum(r["p"] for r in group)/active if active else None))
    return output
