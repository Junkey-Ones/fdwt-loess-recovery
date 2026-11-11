"""识别格点骤旱事件及候选排除记录。输入 M3 候序列，输出 M4 交接。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M4。
日志、路径和退出码由统一入口管理。
"""
from itertools import groupby

def detect_events(rows, params, *, ordered=False):
    """按格点及连续候识别事件，返回事件和候选审计列表。"""
    rules = params["drought"]
    recovery = params["recovery"]["terminate_smp"]
    upper, lower = rules["smp_above"], rules["smp_below"]
    events, audit = [], []
    first_year, last_year = params["time"]["year_start"], params["time"]["year_end"]
    group_key = lambda row: (row["product_combo"], row["grid_id"], row["support_id"])
    if not ordered:
        rows = sorted(rows, key=lambda row: (*group_key(row), row["t_abs"]))
    for key, group in groupby(rows, group_key):
        series = {row["t_abs"]: row for row in group}
        anchor = None
        consumed = -1
        last_t = max(series)
        for t, row in series.items():
            if t <= consumed:
                continue
            value = row["smp"]
            previous = series.get(t - 1, {}).get("smp")
            if previous is None or value is None:
                anchor = None
            if value is None:
                continue
            if value > upper:
                anchor = t
            if not first_year <= row["year"] <= last_year:
                continue
            if value >= upper or (previous is not None and previous < upper):
                continue
            end = t
            while (following := series.get(end + 1, {}).get("smp")) is not None and following < upper:
                end += 1
            minimum = min(range(t, end + 1), key=lambda k: series[k]["smp"])
            low = series[minimum]["smp"]
            rate = (series[anchor]["smp"] - low) / (minimum - anchor) if anchor is not None else None
            stop = minimum + 1
            while (next_smp := series.get(stop, {}).get("smp")) is not None and next_smp <= recovery:
                stop += 1
            termination = stop if next_smp is not None else None
            observed = (termination if termination is not None else stop - 1) - t
            reasons = []
            if low >= lower:
                reasons.append("最低值未低于阈值")
            if rate is None or rate < rules["drop_rate_pct_per_pentad"]:
                reasons.append("下降锚点或速率不合格")
            if observed < rules["min_duration_pentads"] and (termination is not None or stop <= last_t):
                reasons.append("持续不足")
            episode = ":".join(map(str, (*key, t, recovery)))
            active = bool(row.get("active_flag"))
            end_active = termination is not None and bool(series[termination].get("active_flag"))
            risk_active = active and bool(series[minimum].get("active_flag"))
            audit.append(dict(candidate_id=episode, product=key[0], grid_id=key[1], t_s_candidate=t,
                              t_min_candidate=minimum, t_e_candidate=termination, smp_above_anchor=anchor,
                              smp_min=low, development_rate=rate, duration_observed=observed,
                              continuity_ok=True, active_window_ok=active, eligible_main=not reasons,
                              exclusion_reason="；".join(reasons), code_version="0.1.0"))
            if reasons:
                continue
            consumed = end if termination is not None else stop - 1
            last_observed = termination if termination is not None else stop - 1
            deficits = [max(0, upper - series[k]["smp"]) for k in range(t, last_observed+1)]
            censor = None if termination is not None else ("data_end" if stop > last_t else "missing")
            events.append(dict(episode_id=episode, product=key[0], grid_id=key[1], support_id=key[2],
                               grid_version=row.get("grid_version"), soil_product=row.get("soil_product"),
                               precip_product=row.get("precip_product"), phenology_mode=row.get("phenology_mode"),
                               duration_definition="total", termination_rule=str(recovery), year=row["year"],
                               t_s=t, t_min=minimum, t_e=termination, t_s_year=row["year"],
                               t_s_pentad=row["pentad"], t_min_year=series[minimum]["year"],
                               t_min_pentad=series[minimum]["pentad"],
                               t_e_year=series[termination]["year"] if termination is not None else None,
                               t_e_pentad=series[termination]["pentad"] if termination is not None else None,
                               right_censored=termination is None, censor_type=censor,
                               censor_t_abs=stop - 1 if censor else None,
                               duration=observed if not censor else None, observed_duration=observed,
                               development_rate=rate, smp_min=low, mean_deficit=sum(deficits)/len(deficits),
                               max_deficit=max(deficits),
                               route1_A_eligible=active and end_active,
                               recovery_risk_eligible=risk_active,
                               phenology_fallback=row.get("phenology_fallback"),
                               active_window=row.get("active_window_length_L"), land_cover=row.get("land_cover")))
    return events, audit
