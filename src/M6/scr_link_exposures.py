"""连接事件前植被、土壤水和协变量。输入 M3/M5 及年度植被表。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M6。
日志、路径和退出码由统一入口管理。
"""
from collections import defaultdict
import json
from math import cos, isfinite, pi, sin
from random import Random
from statistics import mean, stdev

from src.M3.scr_build_climatology import gringorten

from src.M5.scr_derive_outcomes import index_series, sen_slope


def preceding_mean(series, t, width, field):
    """计算严格早于 t 且无缺候的历史均值。"""
    values = [series.get(k, {}).get(field) for k in range(t-width, t)]
    return mean(values) if values and all(value is not None and isfinite(value) for value in values) else None


def link_exposures(events, rows, vegetation, covariates, params, *, include_audit=True, variant="main"):
    """按事件起始年连接历史暴露，返回长表及暴露簇审计。"""
    settings = params["lai"]
    required = (params["sensitivity"]["lai"]["relaxed_valid_years"] if variant == "lai_four_of_five"
                else settings["main_requires_full"])
    if not 2 <= required <= settings["window_years"]:
        raise ValueError("LAI有效年数门槛必须在2与事件前窗口年数之间。")
    version = "lai_four_of_five" if variant == "lai_four_of_five" else "main"
    if vegetation and not any(row["mask_version"] == settings["mask_version"]
                              and row["qc_version"] == settings["qc_version"] for row in vegetation):
        raise ValueError("植被年表没有当前配置的掩膜及QC版本，不能将旧版输入静默当作全部缺失。")
    annual = {}
    for row in vegetation:
        if (not row["annual_valid"]
                or row["mask_version"] != settings["mask_version"]
                or row["qc_version"] != settings["qc_version"]):
            continue
        if any(row[field] is None or not isfinite(row[field]) or not settings[minimum] <= row[field] <= 1
               for field, minimum in (("temporal_coverage", "annual_time_cover_min"),
                                      ("spatial_coverage", "annual_space_cover_min"))):
            continue
        key = (row["grid_id"], row["year"], row["vegetation_product"], row["phenology_mode"])
        value = row["vegetation_annual_mean"]
        if key in annual or value is None or not isfinite(value):
            raise ValueError(f"植被年值重复或无效：{key}")
        annual[key] = value
    series = index_series(rows)
    width, pre = params["lai"]["window_years"], params["deep"]["pre_pentads"]
    start, stop = params["lai"]["exposure_years"]
    clusters = defaultdict(list)
    distributions = {}
    climate_start, climate_end = params["clim"]["base_window"]
    output = []
    for event in events:
        grid_id, year = event["grid_id"], event["year"]
        t = event["t_s"]
        eligible = start <= year <= stop
        mode = event["phenology_mode"]
        lai = [(y, annual[grid_id, y, "mcd15a3h", mode]) for y in range(year-width, year)
               if (grid_id, y, "mcd15a3h", mode) in annual]
        full = eligible and len(lai) == width
        accepted = eligible and len(lai) >= required
        cluster = f"{grid_id}:{year}" if accepted else None
        if accepted and include_audit:
            clusters[(grid_id, year)].append(event["episode_id"])
        lookup = series[(event["product"], grid_id, event["support_id"])]
        shallow, deep = (preceding_mean(lookup, t, pre, field)
                         for field in ("sm_0_100_mm", "sm_deep_mm"))
        sample_key = (event["product"], grid_id, event["support_id"], event["t_s_pentad"])
        if sample_key not in distributions:
            candidates = [k for k, row in lookup.items()
                          if climate_start <= row["year"] <= climate_end and row["pentad"] == event["t_s_pentad"]]
            distributions[sample_key] = [
                sorted(value for k in candidates if (value := preceding_mean(lookup, k, pre, field)) is not None)
                for field in ("sm_0_100_mm", "sm_deep_mm")]
        shallow_sample, deep_sample = distributions[sample_key]
        climate_settings = {**params["clim"], "min_n": 2}
        shallow_p = gringorten(shallow_sample, shallow, climate_settings)
        deep_p = gringorten(deep_sample, deep, climate_settings)
        spread = stdev(deep_sample) if deep_p is not None and len(deep_sample) > 1 else 0
        deep_z = (deep-mean(deep_sample))/spread if spread else None
        ndvi = [(y, annual[grid_id, y, "mod13q1", mode]) for y in range(year-width, year)
                if (grid_id, y, "mod13q1", mode) in annual]
        ndvi_full = eligible and len(ndvi) == width
        phase = 2*pi*(event["t_s_pentad"]-1)/params["time"]["pentads_per_year"]
        core = {**covariates.get(grid_id, {}), "land_cover": event.get("land_cover"),
                "pentad_sin": sin(phase), "pentad_cos": cos(phase),
                "year_centered_2000": year-params["time"]["index_base_year"],
                "active_window_length_L": event.get("active_window")}
        missing = [name for name in params["covariates"]["core"]
                   if (value := core.get(name)) is None or
                   (name != "land_cover" and not isfinite(value))]
        output.append(dict(core, episode_id=event["episode_id"], exposure_version=version, grid_id=grid_id,
                           year=year, window_start_year=year-width, window_end_year=year-1, window_years=width,
                           LAI_base=mean(value for _, value in lai) if accepted else None,
                           LAI_trend=sen_slope(lai) if accepted else None, LAI_n_valid_years=len(lai),
                           LAI_in_exposure_period=eligible, LAI_required_valid_years=required, LAI_window_eligible=accepted,
                           LAI_valid_years=json.dumps([y for y, _ in lai]),
                           LAI_valid_year_span=lai[-1][0]-lai[0][0] if lai else None,
                           LAI_full_window=full, LAI_exposure_cluster=cluster,
                           LAI_missing_reason=None if accepted else ("历史有效年不足" if eligible else "事件年不在暴露期"),
                           NDVI_base=mean(value for _, value in ndvi) if ndvi_full else None,
                           NDVI_trend=sen_slope(ndvi) if ndvi_full else None, NDVI_n_valid_years=len(ndvi),
                           NDVI_missing_reason=None if ndvi_full else "不在共同期或历史年不全",
                           shallow_SM_pre4=shallow, deep_SM_pre4=deep, deep_SM_pre4_z=deep_z,
                           shallow_SM_pre4_percentile=shallow_p*100 if shallow_p is not None else None,
                           deep_SM_pre4_percentile=deep_p*100 if deep_p is not None else None,
                           deep_window_start_tabs=t-pre, deep_window_end_tabs=t-1,
                           deep_missing_reason=("事件前候不全" if deep is None else
                                                "同候基准不足或零方差" if deep_z is None else None),
                           exposure_complete_L=accepted and not missing, exposure_complete_D=deep_z is not None and not missing,
                           exposure_complete_I=accepted and deep_z is not None and not missing,
                           core_covariate_missing_reason="；".join(missing)))
    return output, audit_clusters(clusters, params, variant=variant)


def audit_clusters(clusters, params, *, variant="main"):
    """使用同一随机种子和全域分母生成格点—年暴露簇审计。"""
    rng = Random(params["random"]["seed"])
    total = sum(map(len, clusters.values()))
    return [dict(analysis_id="lai_four_of_five" if variant == "lai_four_of_five" else "main",
                  LAI_exposure_cluster=f"{grid_id}:{year}", grid_id=grid_id, year=year,
                  n_event=len(ids), cluster_event_fraction=len(ids)/total,
                  selected_event_seed_id=params["random"]["seed_id"], selected_episode_id=rng.choice(sorted(ids)),
                  inverse_cluster_weight=1/len(ids)) for (grid_id, year), ids in sorted(clusters.items())]
