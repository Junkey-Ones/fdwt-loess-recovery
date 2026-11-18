"""M7 发布前核对风险集、年度趋势和事件前暴露支撑，异常阻止冻结。"""
from collections import Counter, defaultdict
from itertools import combinations
import json
from math import isclose
from statistics import median


def require(ok, item):
    """保留可定位的验收失败原因。"""
    if not ok:
        raise ValueError(f"M7验收失败：{item}")


def audit_curve(history, curve, expected=None):
    """独立按事件轨迹计数，核对每候在险、退出、恢复及累计概率。"""
    at, exits, recovered = Counter(), Counter(), Counter()
    last = {}
    for row in history:
        key, step = row["episode_id"], row["followup_pentad"]
        if row["at_risk"]:
            previous = last.get(key)
            require(step == (previous["followup_pentad"] + 1 if previous else 1)
                    and not (previous and (previous["censor_reason"] or previous["recovery_event"])), key)
            at[step] += 1
            recovered[step] += int(row["recovery_event"])
        else:
            require(step == 0 and key not in last, key)
        last[key] = row
    for key, row in last.items():
        require(bool(row["recovery_event"]) != bool(row["censor_reason"]), key)
        exits[row["followup_pentad"]] += 1
    if expected is not None:
        actual = Counter((r["followup_pentad"], "recovered" if r["recovery_event"] else r["censor_reason"]) for r in last.values())
        require(actual == expected, "冻结事件及候表独立复算的入组、恢复或删失不符")
    summary = []
    previous = 0
    for step, row in enumerate(curve, 1):
        require((row["followup_pentad"], row["n_at_risk"], row["n_recovery"]) ==
                (step, at[step], recovered[step]), f"第{step}候风险集")
        require(at[step] - exits[step] == at[step+1], f"第{step}候人数守恒")
        prob = row["cumulative_recovery"]
        if prob is not None:
            require(previous <= prob <= 1, f"第{step}候累计恢复概率")
            previous = prob
        summary.append(dict(step=step, at_risk=at[step], recovered=recovered[step],
                            censored=exits[step]-recovered[step]))
    return summary


def audit_annual(events, annual, trends, params):
    """从条件A事件复算年度分母、中位数、年度Sen斜率和整个家族的Holm调整。"""
    groups = defaultdict(list)
    for event in events:
        if event["route1_A_eligible"]:
            groups[event["year"]].append(event)
    for row in annual:
        sample = groups[row["year"]]
        require(len(sample) == row["n_event"], "年度分母")
        for metric in ("RT", "delta_SMP", "RR"):
            estimate = median(r[metric] for r in sample) if len(sample) >= params["trend"]["year_min_events"] else None
            require(estimate == row[metric], f"{row['year']}年{metric}")
    for row in trends:
        metric = row["metric"]
        points = [(r["year"], r[metric]) for r in annual if r[metric] is not None]
        require(len(points) == row["n_years"], metric)
        if len(points) >= max(3, params["trend"]["min_valid_years"]):
            slope = median((b-a)/(t-s) for (s,a),(t,b) in combinations(points,2))
            require(isclose(slope,row["sen_slope"],abs_tol=1e-12), metric)
    floor = 0
    for i,row in enumerate(sorted((r for r in trends if r["primary_p"] is not None),key=lambda r:r["primary_p"])):
        floor = max(floor,min(1,(len(trends)-i)*row["primary_p"]))
        require(isclose(floor,row["primary_p_holm"]), "Holm")


def four_year_support(exposures, blocks, events, risk):
    """恰四年暴露的原始数、时期资格、方案资格和L/I结局队列分别计数。"""
    by_id = {r["episode_id"]: r for r in events}
    at_risk = {r["episode_id"] for r in risk if r["at_risk"]}
    counts, areas = defaultdict(Counter), defaultdict(set)
    for row in exposures:
        if row.get("LAI_n_valid_years") != 4:
            continue
        start = row["window_start_year"]
        missing, = set(range(start,row["window_end_year"]+1))-set(json.loads(row["LAI_valid_years"]))
        key = (row["year"], missing-start+1, row.get("land_cover") or "unknown")
        n = counts[key]
        n["n_raw"] += 1
        n["n_period"] += int(row["LAI_in_exposure_period"])
        eligible = row["LAI_window_eligible"]
        n["n_event"] += int(eligible)
        block = blocks.get(row["grid_id"])
        if eligible and block is not None:
            areas[key].add(block)
        eid = row["episode_id"]
        event = by_id[eid]
        for model in ("L", "I"):
            complete = eligible and block is not None and row[f"exposure_complete_{model}"]
            n[f"n_recovery_{model}"] += int(complete and eid in at_risk)
            n[f"n_fr_{model}"] += int(complete and event["route1_FR_eligible"] and event["F_R"] is not None)
    return [dict(year=y,missing_position=m,land_cover=c,n_block=len(areas[y,m,c]),**n)
            for (y,m,c),n in sorted(counts.items())]


def model_report(result, details):
    """汇总回执中的实际样本、支撑、区间与条件分支状态。"""
    lines = ["# M7验收", "", details["analysis_scheme"], "",
             "|方案|模型|事件|空间块|成功/请求|失败计数|结果|",
             "|---|---|---:|---:|---:|---|---|"]
    for row in result["model_fit_manifest"] + result["sensitivity_model_manifest"]:
        level = row["inference_level"]
        if level in ("formal", "sensitivity_interval"):
            status = "计算通过，区间已放行"
        elif level == "point_estimate":
            status = "仅保留点估计：" + (row.get("inference_warning") or "联合区间未放行")
        elif row.get("support_gate") != "passed":
            status = "支撑不足，未拟合"
        else:
            status = "验收失败：" + str(row.get("convergence_status"))
        lines.append(f"|{row.get('sensitivity','本方案')}|{row['analysis_id']}|{row['n_event']}|"
                     f"{row.get('n_resampling_block')}|{row.get('bootstrap_success')}/{row.get('bootstrap_requested')}|"
                     f"{row.get('bootstrap_failure_counts') or '—'}|{status}|")
    for row in details["ipcw_applicability"]:
        lines.append(f"- IPCW {row['version']}：{row['status']}")
    for model,status in details["firth_applicability"].items():
        lines.append(f"- Firth {model}：{status}")
    return "\n".join(lines) + "\n"


def source_counts(events, rows, horizon, version):
    """从冻结事件与连续候独立确定最后一次观测和结局，用于检查入组及截断。"""
    from math import isfinite
    series = defaultdict(dict)
    for r in rows:
        series[r["product_combo"],r["grid_id"],r["support_id"]][r["t_abs"]] = r
    counts = Counter()
    for e in events:
        if version == "main" and e["route1_A_eligible"]:
            source = series[e["product"],e["grid_id"],e["support_id"]]
            low, end = e["t_min"], e["t_e"]
            delta = source[end]["smp"] - source[low]["smp"]
            require(end > low and e["RT"] == end-low and isclose(e["delta_SMP"],delta,abs_tol=1e-8)
                    and isclose(e["RR"],delta/(end-low),abs_tol=1e-8), f"恢复指标或量纲：{e['episode_id']}")
        if not e["recovery_risk_eligible"]:
            continue
        lookup = series[e["product"],e["grid_id"],e["support_id"]]
        length = 0
        reason = "administrative"
        for step in range(1,horizon+1):
            t = e["t_min"]+step
            r = lookup.get(t,{})
            if r.get("smp") is None or not isfinite(r["smp"]):
                reason = "data_end" if t > max(lookup) else "missing"
                break
            if version == "active_window" and r.get("active_flag") is not True:
                reason = "phenology_missing" if r.get("active_flag") is None else "season_end"
                break
            length = step
            if t == e["t_e"]:
                reason = "recovered"
                break
        if version != "complete_followup" or reason in ("administrative","recovered"):
            counts[length,reason] += 1
    return counts
