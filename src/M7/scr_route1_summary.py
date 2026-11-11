"""构建路线一风险集及主描述。输入 M3/M5；输出风险表、分布和比例。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M7。
日志、路径和退出码由统一入口管理。
"""
from collections import Counter, defaultdict
from itertools import combinations
from math import erfc, sqrt
from statistics import NormalDist, mean, median, quantiles

from src.M5.scr_derive_outcomes import index_series, sen_slope


def recovery_risk(events, rows, params, *, horizon=None):
    """从 t_min 展开风险集，首次缺测后停止随访。"""
    index = index_series(rows)
    horizon = params["route1"]["recovery_risk_h"] if horizon is None else horizon
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
        q1[-1].update(RT_q25=None, RT_q75=None, delta_SMP_mean=None, RR_mean=None)
        if enough:
            q25, _, q75 = quantiles([row["RT"] for row in rows], method="inclusive")
            q1[-1].update(RT_q25=q25, RT_q75=q75, delta_SMP_mean=mean(row["delta_SMP"] for row in rows),
                          RR_mean=mean(row["RR"] for row in rows))
        known = [row for row in rows if row["F_R"] is not None]
        positive = sum(row["F_R"] is True for row in known)
        q2.append(dict(year=year, n_recovered=len(rows), n_known=len(known), n_positive=positive,
                       n_unknown=len(rows)-len(known), proportion=positive/len(known) if known else None))
    return q1, q2


def summarize_lags(events):
    """分别汇总两个阳性样本的候差和 F_R 相对终止候的分布。"""
    result = []
    for metric, flag, condition_a in (("Lag_FR", "F_R", True), ("Offset_FR", "F_R", True),
                                      ("Lag_P", "P_term", False)):
        sample = [row for row in events if (not condition_a or row["route1_A_eligible"])
                  and row.get(flag) is True]
        values = [row.get(metric) for row in sample]
        if None in values:
            raise ValueError(f"阳性事件缺少候差：{metric}")
        middle = median(values) if values else None
        q25, _, q75 = quantiles(values, method="inclusive") if len(values) > 1 else (middle,) * 3
        result.append(dict(metric=metric, domain="condition_A" if condition_a else "all_positive",
                           n_event=len(values), median=middle, q25=q25, q75=q75))
    return result


def centered_autocorrelations(values):
    """计算以全序列离均差平方和为分母的样本自相关。"""
    center = mean(values)
    centered = [value - center for value in values]
    denominator = sum(value * value for value in centered)
    return [sum(a * b for a, b in zip(centered, centered[lag:])) / denominator if denominator else 0.0
            for lag in range(1, len(values))]


def average_ranks(values):
    """为并列值赋平均秩，返回原序列顺序。"""
    ranks = {}
    counts = Counter(values)
    start = 1
    for value, count in sorted(counts.items()):
        ranks[value] = start + (count - 1) / 2
        start += count
    return [ranks[value] for value in values]


def mk_p_value(score, variance):
    """对 MK 统计量作连续性修正后计算双侧概率。"""
    if score == 0:
        return 1.0
    return erfc((abs(score) - 1) / sqrt(2 * variance)) if variance > 0 else None


def trend_estimates(annual, params, *, minimum_years=None):
    """估计 Sen 斜率，按 Ljung–Box 决定主检验并保留 Hamed–Rao 敏感性。"""
    settings = params["trend"]
    annual = tuple(annual)
    if minimum_years is None:
        minimum_years = settings["min_valid_years"]
    prefix, cutoff = settings["autocorr_trigger"].split("<")
    if prefix != "ljung_box_lag1_p" or not 0 < float(cutoff) < 1:
        raise ValueError("趋势自相关触发规则须为 lag-1 Ljung–Box 概率阈值。")
    cutoff = float(cutoff)
    result = []
    for metric in ("RT", "delta_SMP", "RR"):
        points = sorted((row["year"], row[metric]) for row in annual if row[metric] is not None)
        n = len(points)
        row = dict(metric=metric, n_years=n, status="insufficient_years", sen_slope=None,
                   p_mk=None, p_hamed_rao=None, ljung_box_lag1_p=None, variance_factor=None,
                   primary_test=None, primary_p=None)
        result.append(row)
        if n < max(3, minimum_years):
            continue
        years, values = zip(*points)
        if len(set(years)) != n:
            raise ValueError("年度趋势输入包含重复年份。")
        slope = sen_slope(points)
        score = sum(int(b > a) - int(b < a) for a, b in combinations(values, 2))
        tie_term = sum(k * (k - 1) * (2 * k + 5) for k in Counter(values).values())
        variance = (n * (n - 1) * (2 * n + 5) - tie_term) / 18
        row.update(sen_slope=slope, p_mk=mk_p_value(score, variance))
        if years[-1] - years[0] + 1 != n:
            row["status"] = "annual_gaps"
            continue
        lag_one = centered_autocorrelations(values)[0]
        q = n * (n + 2) * lag_one ** 2 / (n - 1)
        diagnostic = erfc(sqrt(q / 2))
        residual_ranks = average_ranks([value - slope * (year - years[0]) for year, value in points])
        significance_bound = NormalDist().inv_cdf(0.975) / sqrt(n)
        weighted_acf = sum((n - lag) * (n - lag - 1) * (n - lag - 2) * correlation
                           for lag, correlation in enumerate(centered_autocorrelations(residual_ranks), 1)
                           if abs(correlation) > significance_bound)
        factor = 1 + 2 * weighted_acf / (n * (n - 1) * (n - 2))
        corrected = mk_p_value(score, variance * factor)
        use_correction = diagnostic < cutoff
        p_value = corrected if use_correction else row["p_mk"]
        row.update(p_hamed_rao=corrected, ljung_box_lag1_p=diagnostic, variance_factor=factor,
                   primary_test="hamed_rao" if use_correction else "mann_kendall", primary_p=p_value,
                   status="passed" if p_value is not None else "invalid_variance")
    for row, adjusted in zip(result, holm([row["primary_p"] for row in result])):
        row["primary_p_holm"] = adjusted
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
