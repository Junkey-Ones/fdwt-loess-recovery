"""派生恢复、降水窗口及湿急转分支。输入 M3/M4，输出 M5 事件表和长表。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M5。
日志、路径和退出码由统一入口管理。
"""
from statistics import median


def sen_slope(points):
    """返回按时间差计算的 Theil–Sen 斜率。"""
    slopes = [(b - a) / (j - i) for index, (i, a) in enumerate(points)
              for j, b in points[index + 1:] if i != j]
    return median(slopes) if slopes else None


def index_series(rows):
    """建立产品、支撑、格点及连续候索引。"""
    result = {}
    for row in rows:
        key = (row["product_combo"], row["grid_id"], row["support_id"])
        result.setdefault(key, {})[row["t_abs"]] = row
    return result


def precip_qualifies(row, minimum):
    """按同产品阈值判定降水候，缺测时返回未知。"""
    p, threshold = row.get("p_mm"), row.get("p95_mm")
    if p is None or threshold is None or not row.get("p95_usable"):
        return None
    return p > minimum and p >= threshold


def first_positive(values):
    """完整窗口内取首次阳性，缺一候则返回未知。"""
    if not values or any(value is None for value in values.values()):
        return None, None
    first = next((t for t, value in values.items() if value), None)
    return first is not None, first


def event_window(specification, minimum, end):
    """把冻结窗口锚点转换为包含两端的候范围。"""
    limits = []
    for expression in specification:
        if expression == "t_min":
            limits.append(minimum)
        elif expression.startswith("t_e"):
            limits.append(end + int(expression[3:] or "0"))
        else:
            raise ValueError(f"未识别的事件窗口锚点：{expression}")
    return range(limits[0], limits[1]+1)


def derive_outcomes(events, rows, params):
    """计算事件结局与轨迹、极端降水及分支长表。"""
    series = index_series(rows)
    master, precipitation, branches, trajectories = [], [], [], []
    for event in events:
        result = event.copy()
        key = (event["product"], event["grid_id"], event["support_id"])
        lookup = series[key]
        minimum, end = event["t_min"], event["t_e"]
        stop = end if end is not None else event["censor_t_abs"]
        early = params["recovery"]["early_pentads"]
        post = params["recovery"]["post_te_trajectory"]
        for t in range(minimum, stop + (max(post) if end is not None else 0) + 1):
            row = lookup.get(t, {})
            trajectories.append(dict(episode_id=event["episode_id"], t_abs=t, relative_to_tmin=t-minimum,
                                     relative_to_te=t-end if end is not None else None, smp=row.get("smp"),
                                     recovery_phase_flag=t <= stop, early_recovery_flag=minimum < t <= min(stop, minimum+early),
                                     post_te_flag=t > stop, active_flag=row.get("active_flag"), qc_status=row.get("qc_status")))
        for name in ("P_term", "F_R", "F_Z"):
            result.update({name: None, f"{name}_status": "unknown"})
        if end is None:
            master.append(result)
            continue
        low = lookup[minimum]["smp"]
        delta = lookup[end]["smp"] - low
        points = [(t, lookup[t]["smp"]) for t in range(minimum, end + 1)]
        result.update(RT=end-minimum, delta_SMP=delta, RR=delta/(end-minimum),
                      recovery_slope=sen_slope(points),
                      early_recovery_rate=(lookup[minimum+early]["smp"]-low)/early if minimum+early <= end else None)
        windows = {name: event_window(params[key]["window"], minimum, end)
                   for name, key in (("P_term", "pterm"), ("F_R", "fr"), ("F_Z", "fz"))}
        amounts = [lookup.get(t, {}).get("p_mm") for t in windows["P_term"]]
        result["pterm_total_mm"] = sum(amounts) if amounts and None not in amounts else None
        result["pterm_max_mm"] = max(amounts) if amounts and None not in amounts else None
        first = {}
        for name, window in windows.items():
            values = {}
            for t in window:
                row = lookup.get(t, {})
                if name == "F_Z":
                    w1, w2 = lookup.get(t-1, {}).get("w"), row.get("w")
                    values[t] = None if w1 is None or w2 is None else w1 < 0 and w2 >= params["fz"]["w2_threshold"]
                else:
                    values[t] = precip_qualifies(row, params["pterm" if name == "P_term" else "fr"]["min_p_mm"])
            flag, first[name] = first_positive(values)
            result[name] = flag
            result[f"{name}_status"] = "unknown" if flag is None else ("positive" if flag else "negative")
        tp, tr = first["P_term"], first["F_R"]
        result.update(t_P95=tp, Lag_P=tp-minimum if tp is not None else None, t_w_R=tr,
                      Lag_FR=tr-minimum if tr is not None else None, Offset_FR=tr-end if tr is not None else None,
                      F_R_subtype=None if tr is None else ("pre" if tr < end else "sync" if tr == end else "post"))
        for t in sorted(set(windows["P_term"]) | set(windows["F_R"])):
            row = lookup.get(t, {})
            if not precip_qualifies(row, params["fr"]["min_p_mm"]):
                continue
            precipitation.append(dict(episode_id=event["episode_id"], t_abs=t, p_term_definition="main",
                                      year=row["year"], pentad=row["pentad"], p_mm=row["p_mm"], p95_mm=row["p95_mm"],
                                      p95_qualify=True, in_pterm_window=t in windows["P_term"],
                                      in_fr_window=t in windows["F_R"], is_first_pterm=t == tp, is_first_fr=t == tr,
                                      pentad73_flag=row["pentad"] == params["time"]["pentads_per_year"]))
        for name in ("F_R", "F_Z"):
            t = first[name]
            if t is None:
                continue
            w1, w2 = lookup.get(t-1, {}).get("w"), lookup[t].get("w")
            eligible = w1 is not None and w2 is not None and w1 < 0 < w2
            alpha = params["dfai"]["alpha"]
            branches.append(dict(episode_id=event["episode_id"], branch=name, branch_definition="main", t_w=t,
                                 W1=w1, W2=w2, DFAI_alpha=alpha, E2a_eligible=eligible,
                                 DFAI=(w2-w1)*(abs(w2)+abs(w1))*alpha**(-abs(w1)) if eligible else None,
                                 window_status="positive", branch_available=True))
        master.append(result)
    return master, precipitation, branches, trajectories
