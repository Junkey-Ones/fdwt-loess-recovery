"""核对多年物候门槛和跨年气候态基准期边界。"""
from datetime import date
from src.M3.scr_prepare_support import prepare_support
from src.M3.scr_build_climatology import build_climatology
from workflow.run_module import DEFAULT_CONFIG, load_config


def test_sparse_dynamic_and_fixed():
    p = load_config(DEFAULT_CONFIG)
    grid = [dict(grid_id="g",grid_version="v")]
    seasons = [dict(year=y,valid_pixel_area_frac=1,valid_native_pixels=100,
                    segments=[[f"{y}-04-01",f"{y}-09-30"]]) for y in range(2003,2008)]
    record = dict(grid_id="g",valid_landcover_years=21,vegetation_area_frac=1,native_exclude_frac=0,
                  baseline_land_cover="forest",phenology=seasons[:-1])
    def windows(variant):
        return prepare_support([record],grid,p,variant)[0]["g"]["windows"]
    assert not any(segments for segments,_ in windows("main").values())
    assert windows("fixed_season")[2003][0]
    record["phenology"] = seasons
    assert windows("lai_four_of_five")[2003][1] is False
    assert windows("main")[2008][1] is True


def test_neighbors_stay_in_baseline():
    p = load_config(DEFAULT_CONFIG)
    p["clim"].update(base_window=[2003,2004],min_n=1,p95_min_nonzero_n=1)
    rows = []
    for year in range(2002,2006):
        for pentad in (1,2,72,73):
            value = (year-2002)*100+pentad
            rows.append(dict(year=year,pentad=pentad,grid_id="g",grid_version="v",p_mm=value,
                             balance_mm=value,sm_0_100_mm=value,t_abs=year*73+pentad,
                             start_date=date(year,1,1),end_date=date(year,1,5)))
    support = {"g":dict(mask_include=True,windows={},phenology_mode="dynamic")}
    climate,_,_ = build_climatology(rows,support,p,"era5land__era5land")
    import numpy as np
    for index,expected in ((0,[101,102,173,201,202]),(-1,[172,173,201,272,273])):
        assert climate[index]["p_n"] == len(expected)
        assert climate[index]["p95_mm"] == np.percentile(expected,p["fr"]["percentile"])
