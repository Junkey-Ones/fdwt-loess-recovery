"""只读Q1曲线验收，重建三个随访期并记录区间；不发布正式M7。"""
import json
from pathlib import Path
from collections import defaultdict
from itertools import groupby
import pyarrow.parquet as pq
from workflow.run_module import load_config, DEFAULT_CONFIG
from src.M7.scr_route1_summary import recovery_risk
from src.M7.scr_fit_recovery_risk import recovery_time_baseline
from src.M7.scr_q1_diagnostics import followup_subset, censor_audit, annual_companions
from src.M7.scr_route1_summary import trend_estimates


def main():
    """读取既有冻结数据，验证点估计不变与自举成功率。"""
    root = Path(__file__).resolve().parents[1]
    source = "2026-11-16_主分析LAI4of5"
    base = root / "data/frozen/downstream" / source
    params = load_config(DEFAULT_CONFIG)
    events = pq.read_table(base / "M5/event_master.parquet").to_pylist()
    groups = defaultdict(list)
    for event in events:
        groups[event["grid_id"]].append(event)
    blocks = {r["grid_id"]:r["block_id"] for r in pq.read_table(
        root / "data/interim/era5land_base" / source / "grid_manifest.parquet").to_pylist()}
    superblocks = {r["block_id"]:r["superblock_id"] for r in pq.read_table(base / "M5/superblock_membership.parquet").to_pylist()}
    horizons = {"main":params["route1"]["recovery_risk_h"], **params["sensitivity"]["followup"]}
    risks = {k:[] for k in horizons}
    table = pq.read_table(base / "M3/grid_pentad.parquet", columns=["product_combo", "grid_id", "support_id", "t_abs", "smp", "active_flag"],
                          filters=[("grid_id", "in", sorted(groups))]).sort_by([("grid_id", "ascending"), ("t_abs", "ascending")])
    rows = (r for batch in table.to_batches(max_chunksize=8192) for r in batch.to_pylist())
    for i, (grid, values) in enumerate(groupby(rows, key=lambda r:r["grid_id"])):
        values = list(values)
        for key,h in horizons.items():
            risks[key].extend(recovery_risk(groups[grid], values, params, horizon=h))
        if i%1000 == 0:
            print("risk grids",i,flush=True)
    audit = {"source_alias":source,"purpose":"numerical_validation_only","curves":{}}
    for key in params["route1"]["q1_censor_sensitivities"]:
        risks[key] = followup_subset(risks["main"],key)
        horizons[key] = horizons["main"]
    for key,h in horizons.items():
        curve,support = recovery_time_baseline(risks[key],events,blocks,h,params["route1"]["recovery_time_df"],params["infer"],
                                               params=params,superblocks=superblocks)
        original = pq.read_table(base / "M7" / ("q1_recovery_risk.parquet" if key=="main" else "q1_recovery_risk_sensitivity.parquet")).to_pylist()
        if key!="main":original=[r for r in original if r["version"]==key]
        equal=(all(all(a[k]==b[k] for k in ("followup_pentad","n_at_risk","n_recovery","hazard","cumulative_recovery")) for a,b in zip(curve,original)) and len(curve)==len(original)) if original else None
        audit["curves"][key]={"H":h,"point_estimates_exact_match":equal,"support":support,"rows":curve}
        print(key,"matched",equal,"success",support["bootstrap_success"],"last",curve[-1],flush=True)
    audit["censor_audit"] = [r for key,h in horizons.items() for r in censor_audit(risks[key],events,key,h,params)]
    audit["companions"] = annual_companions(pq.ParquetFile(base / "M3/grid_pentad.parquet").iter_batches(columns=[
        "grid_id","year","active_flag","active_window_length_L","phenology_fallback","smp","p_mm"]),
        pq.read_table(base / "M3/grid_mask.parquet").to_pylist(),events,params)
    audit["companion_trends"] = trend_estimates(audit["companions"],params,
        metrics=("mean_active_pentads","n_a","phenology_fallback_rate","smp_completeness","precip_completeness"))
    path=root / "metadata/local/q1_extended_validation_20261117.json"
    path.write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
