"""汇总 M2 日数据中的背景气候协变量。输出逐格点年均降水和暖季均温。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M6。
日志、路径和退出码由统一入口管理。
"""
from collections import defaultdict
from datetime import date


def background_climate(batches, params):
    """逐批汇总日降水和暖季温度，完整期不足时保留缺失。"""
    first, last = params["covariates"]["climate_years"]
    first_month, last_month = params["phenology"]["fixed_months"]
    sums = defaultdict(lambda: [0.0, 0, 0.0, 0])
    for batch in batches:
        for row in batch:
            day = row["date"]
            if not first <= day.year <= last:
                continue
            stats = sums[row["grid_id"]]
            if row["p_mm"] is not None:
                stats[0] += row["p_mm"]
                stats[1] += 1
            if first_month <= day.month <= last_month and row["t2m_c"] is not None:
                stats[2] += row["t2m_c"]
                stats[3] += 1
    days = (date(last+1, 1, 1)-date(first, 1, 1)).days
    warm_days = sum((date(y, last_month+1, 1)-date(y, first_month, 1)).days for y in range(first, last+1))
    return {grid: dict(annual_p_mean_mm=p/(last-first+1) if n == days else None,
                       apr_sep_t2m_mean_c=temp/n_temp if n_temp == warm_days else None)
            for grid, (p, n, temp, n_temp) in sums.items()}
