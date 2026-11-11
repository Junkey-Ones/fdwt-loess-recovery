"""编码路线二首次离场及样本门槛。输入 M3/M5，输出 M8 随访与出口。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M8。
日志、路径和退出码由统一入口管理。
"""
from collections import Counter

from src.M5.scr_derive_outcomes import index_series, precip_qualifies


def encode_exits(events, rows, params, blocks=None, *, horizon=None, version="main"):
    """从事件起点随访，未知接续单列，C 只在完整 H 时编码。"""
    h = params["route2"]["h"] if horizon is None else horizon
    series = index_series(rows)
    last_by_grid = {key: max(lookup) for key, lookup in series.items()}
    person, exits = [], []
    for event in events:
        start, end = event["t_s"], event["t_e"]
        key = (event["product"], event["grid_id"], event["support_id"])
        lookup = series[key]
        extreme = False
        last_t = last_by_grid[key]
        for step in range(1, h+1):
            t = start + step
            row = lookup.get(t, {})
            smp = row.get("smp")
            recovery = t == end
            wet = precip_qualifies(row, params["fr"]["min_p_mm"])
            unknown = recovery and event.get("F_R") is None
            reason = ("unknown_fr" if unknown else "data_end" if t > last_t
                      else "missing_smp" if smp is None else None)
            exit_type = None
            if reason is None:
                if recovery:
                    exit_type = "B" if event["F_R"] else "A"
                elif step == h:
                    exit_type = "C"
            extreme |= bool(wet) and not recovery
            person.append(dict(episode_id=event["episode_id"], t0_ts=start, followup_pentad=step,
                               t_abs=t, at_risk=smp is not None and not unknown, exit_A=exit_type=="A",
                               exit_B=exit_type=="B", exit_C_at_H=exit_type=="C", censored=reason is not None,
                               censor_reason=reason, exit_type_unknown=unknown, smp_tv=smp,
                               p95_flag_tv=wet, recovery_this_pentad=recovery, fr_type_known=recovery and not unknown,
                               extreme_without_recovery=bool(wet) and not recovery,
                               F_R_subtype=event.get("F_R_subtype") if recovery else None,
                               first_exit_t_abs=t if exit_type else None))
            if reason or exit_type:
                strict = exit_type == "B" and event.get("F_R_subtype") == "post"
                exits.append(dict(episode_id=event["episode_id"], route2_version=version, H=h,
                                  exit_type=exit_type, exit_time=step if exit_type else None,
                                  censored=reason is not None, censor_time=step if reason else None,
                                  censor_reason=reason, exit_type_unknown=unknown, exit_A_strict=exit_type=="A" or strict,
                                  strict_reclass_from_B=strict, extreme_without_recovery_ever=extreme,
                                  followup_complete=reason is None))
                break
    counts = Counter(row["exit_type"] for row in exits)
    blocks = blocks or {}
    event_blocks = {row["episode_id"]: blocks.get(row["grid_id"]) for row in events}
    observed_blocks = {event_blocks[row["episode_id"]] for row in exits if row["exit_type"] is not None}
    observed_blocks.discard(None)
    reasons = []
    if counts["B"] < params["route2"]["exit_b_min"]:
        reasons.append("B 出口数不足")
    if len(observed_blocks) < params["route2"]["exit_blocks_min"]:
        reasons.append("可用空间块不足")
    gate = {"counts": {name: counts[name] for name in ("A", "B", "C")}, "n_blocks": len(observed_blocks),
            "n_censored": counts[None], "status": "exited" if reasons else "descriptive_only",
            "reasons": reasons}
    return person, exits, gate
