"""构建路线一风险集及主描述。输入 M3/M5；输出风险表、分布和比例。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M7。
日志、路径和退出码由统一入口管理。
"""
from collections import defaultdict
from statistics import median

from src.M5.scr_derive_outcomes import index_series, sen_slope


def recovery_risk(events, rows, params):
    """从 t_min 展开风险集，首次缺测后停止随访。"""
    index = index_series(rows)
    horizon = params["route1"]["recovery_risk_h"]
    risk = []
    for event in events:
        if not event["recovery_risk_eligible"]:
            continue
        lookup = index[event["product"], event["grid_id"], event["support_id"]]
        start, end = event["t_min"], event["t_e"]
        for step in range(1, horizon+1):
            t = start + step
            row = lookup.get(t, {})
            if row.get("smp") is None:
                if step > 1:
                    reason = "data_end" if t > max(lookup) else "missing"
                    risk[-1].update(censor_missing=reason=="missing", censor_data_end=reason=="data_end",
                                    censor_reason=reason, last_valid_t_abs=t-1)
                else:
                    reason = "data_end" if t > max(lookup) else "missing"
                    risk.append(dict(episode_id=event["episode_id"], t0_tmin=start, followup_pentad=0,
                                     t_abs=start, at_risk=False, recovery_event=False, censor_administrative=False,
                                     censor_missing=reason=="missing", censor_data_end=reason=="data_end",
                                     censor_reason=reason, last_valid_t_abs=start))
                break
            observed = end == t
            admin = step == horizon and not observed
            risk.append(dict(episode_id=event["episode_id"], t0_tmin=start, followup_pentad=step,
                             t_abs=t, at_risk=True, recovery_event=observed, censor_administrative=admin,
                             censor_missing=False, censor_data_end=False, censor_reason="administrative" if admin else None,
                             last_valid_t_abs=t, smp=row["smp"], active_flag=row.get("active_flag"),
                             exposure_version="main", analysis_weight=1.0))
            if observed:
                break
    return risk


def summarize(events, params):
    """按年计算条件 A 恢复中位数、已知接续比例及未知数。"""
    groups = defaultdict(list)
    for row in events:
        if row["route1_A_eligible"]:
            groups[row["year"]].append(row)
    q1, q2 = [], []
    for year in range(params["time"]["year_start"], params["time"]["year_end"]+1):
        rows = groups[year]
        enough = len(rows) >= params["trend"]["year_min_events"]
        q1.append(dict(year=year, n_event=len(rows),
                       **{metric: median(row[metric] for row in rows) if enough else None
                          for metric in ("RT", "delta_SMP", "RR")}))
        known = [row for row in rows if row["F_R"] is not None]
        positive = sum(row["F_R"] is True for row in known)
        q2.append(dict(year=year, n_recovered=len(rows), n_known=len(known), n_positive=positive,
                       n_unknown=len(rows)-len(known), proportion=positive/len(known) if known else None))
    return q1, q2


def trend_estimates(annual, params):
    """按有效年门槛估计 Sen 斜率，保存未执行推断的状态。"""
    result = []
    for metric in ("RT", "delta_SMP", "RR"):
        points = [(row["year"], row[metric]) for row in annual if row[metric] is not None]
        eligible = len(points) >= params["trend"]["min_valid_years"]
        result.append(dict(metric=metric, n_years=len(points),
                           sen_slope=sen_slope(points) if eligible else None,
                           status="descriptive_only" if eligible else "insufficient_years"))
    return result


def holm(p_values):
    """保持家族大小，以缺失项占位并返回原次序调整值。"""
    ordered = sorted((value, i) for i, value in enumerate(p_values) if value is not None)
    adjusted = [None] * len(p_values)
    previous = 0.0
    for rank, (value, index) in enumerate(ordered):
        previous = min(1.0, max(previous, (len(p_values)-rank)*value))
        adjusted[index] = previous
    return adjusted
