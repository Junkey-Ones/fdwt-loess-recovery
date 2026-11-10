"""按格点建立气候态和活跃候交接。输入 M2 候表及已验收空间支撑。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M3。
日志、路径和退出码由统一入口管理。
"""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from statistics import NormalDist

import numpy as np


def gringorten(values, value, settings):
    """按平均秩或插入位置返回裁剪后的经验概率。"""
    if value is None or len(values) < settings["min_n"]:
        return None
    left = bisect_left(values, value)
    right = bisect_right(values, value)
    rank = (left + right + 1) / 2
    probability = (rank - settings["gringorten_a"]) / (len(values) + settings["gringorten_b"])
    eps = settings["normal_p_eps"]
    return min(1 - eps, max(eps, probability))


def build_climatology(rows, support, params, combo):
    """逐格点计算同产品阈值，返回气候态、连续候和活跃候。"""
    settings = params["clim"]
    first, last = settings["base_window"]
    count = params["time"]["pentads_per_year"]
    soil, rain = combo.split("__")
    grid = defaultdict(list)
    for row in rows:
        grid[row["grid_id"]].append(row)
    climate, pentads, active = [], [], []
    for grid_id, group in grid.items():
        if grid_id not in support:
            continue
        info = support[grid_id]
        if not info["mask_include"]:
            continue
        buckets = defaultdict(list)
        for row in group:
            if first <= row["year"] <= last:
                buckets[row["pentad"]].append(row)
        pools = {}
        for p in range(1, count+1):
            sample = [row for offset in settings["pentad_pool"]
                      for row in buckets[(p + offset - 1) % count + 1]]
            sm, rain_values, balance = (
                sorted(row[field] for row in sample if row.get(field) is not None)
                for field in ("sm_0_100_mm", "p_mm", "balance_mm"))
            positive = sum(value > 0 for value in rain_values)
            threshold = float(np.percentile(rain_values, params["fr"]["percentile"])) if len(rain_values) >= settings["min_n"] else None
            usable = threshold is not None and threshold > 0 and positive >= settings["p95_min_nonzero_n"]
            pools[p] = sm, rain_values, balance, threshold, positive, usable
            climate.append(dict(product_code=combo, grid_version=group[0]["grid_version"], grid_id=grid_id,
                                pentad=p, clim_version="main", clim_start_year=first, clim_end_year=last,
                                sm_n=len(sm), balance_n=len(balance), p_n=len(rain_values), p_nonzero_n=positive,
                                p_zero_fraction=1-positive/len(rain_values) if rain_values else None,
                                p95_mm=threshold, p95_usable=usable,
                                climatology_qc_status="passed" if len(sm) >= settings["min_n"] else "insufficient"))
        windows = info["windows"]
        by_year = defaultdict(list)
        for row in group:
            by_year[row["year"]].append(row)
        for year, annual in by_year.items():
            intervals, fallback = windows.get(year, ([], None))
            flags = {row["t_abs"]: any(row["start_date"] <= end and row["end_date"] >= start
                                      for start, end in intervals) for row in annual}
            length = sum(flags.values())
            for row in annual:
                sm, rain_values, balance, threshold, positive, usable = pools[row["pentad"]]
                smp = gringorten(sm, row.get("sm_0_100_mm"), settings)
                probability = gringorten(balance, row.get("balance_mm"), settings)
                state = dict(grid_version=row["grid_version"], grid_id=grid_id, t_abs=row["t_abs"],
                             year=year, pentad=row["pentad"], phenology_mode=info["phenology_mode"],
                             active_flag=flags[row["t_abs"]], active_window_length_L=length,
                             phenology_fallback=fallback)
                active.append(state)
                pentads.append({**row, **state, "product_combo": combo, "soil_product": soil,
                                "precip_product": rain, "clim_version": "main",
                                "land_cover": info.get("land_cover"),
                                "smp": smp * settings["smp_multiplier"] if smp is not None else None,
                                "sm_rank_n": len(sm), "p95_mm": threshold, "p95_n": len(rain_values),
                                "p_nonzero_n": positive, "p95_usable": usable,
                                "balance_rank_n": len(balance), "balance_p": probability,
                                "w": NormalDist().inv_cdf(probability) if probability is not None else None})
    return climate, pentads, active
