"""汇总 M2 日数据中的背景气候协变量。输出逐格点年均降水和暖季均温。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M6。
日志、路径和退出码由统一入口管理。
"""
from collections import defaultdict
from datetime import date


def background_climate(batches, params):
    """逐批汇总日降水和暖季温度，完整期不足时保留缺失。"""
    import numpy as np
    import pyarrow.compute as pc

    first, last = params["covariates"]["climate_years"]
    first_month, last_month = params["phenology"]["fixed_months"]
    sums = defaultdict(lambda: [0.0, 0, 0.0, 0])
    start = date(first, 1, 1)
    days = (date(last+1, 1, 1)-start).days
    grid_indices = {}
    observed = np.zeros((0, days), dtype=bool)
    for batch in batches:
        dates = batch.column("date")
        years = pc.year(dates).to_numpy()
        keep = (years >= first) & (years <= last)
        keys = batch.column("grid_id").filter(keep).dictionary_encode()
        names = keys.dictionary.to_pylist()
        if not names:
            continue
        codes = keys.indices.to_numpy()
        offsets = dates.cast("date32").cast("int32").to_numpy()[keep] - (start - date(1970, 1, 1)).days
        grid_codes = np.array([grid_indices.setdefault(name, len(grid_indices)) for name in names])[codes]
        if len(grid_indices) > len(observed):
            capacity = max(len(grid_indices), 2 * len(observed))
            expanded = np.zeros((capacity, days), dtype=bool)
            expanded[:len(observed)] = observed
            observed = expanded
        positions = grid_codes * days + offsets
        unique_positions, counts = np.unique(positions, return_counts=True)
        seen = observed.ravel()
        duplicate = (counts > 1) | seen[unique_positions]
        if duplicate.any():
            grid_index = unique_positions[duplicate][0] // days
            name = next(name for name, index in grid_indices.items() if index == grid_index)
            raise ValueError(f"背景气候日表含重复格点日期：{name}")
        seen[unique_positions] = True
        months = pc.month(dates).to_numpy()[keep]
        current = np.array([sums[name] for name in names])
        for field, index, season in (("p_mm", 0, True),
                                     ("t2m_c", 2, (months >= first_month) & (months <= last_month))):
            column = batch.column(field).filter(keep)
            values = column.to_numpy()
            selected = np.isfinite(values) & season
            np.add.at(current[:, index], codes[selected], values[selected])
            np.add.at(current[:, index + 1], codes[selected], 1)
        sums.update(zip(names, current))
    warm_days = sum((date(y + (last_month == 12), last_month % 12 + 1, 1)
                     - date(y, first_month, 1)).days for y in range(first, last+1))
    return {grid: dict(annual_p_mean_mm=p/(last-first+1) if n == days else None,
                       apr_sep_t2m_mean_c=temp/n_temp if n_temp == warm_days else None)
            for grid, (p, n, temp, n_temp) in sums.items()}
