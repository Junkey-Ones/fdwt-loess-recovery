"""只读验收新增M7敏感性；仅写metadata/local，不发布正式结果。"""
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
import csv
import hashlib
import json
from pathlib import Path
import pyarrow.parquet as pq
from workflow.run_module import load_config, DEFAULT_CONFIG
from workflow.freeze_m0 import atomic_write, json_bytes
from src.M7.scr_model_sensitivity import fit_sensitivity
from src.M7.scr_block_sensitivity import fixed_blocks
from src.M1.scr_audit_era5land import digest
from src.M7.scr_route1_summary import recovery_risk
from src.M7.scr_q1_diagnostics import followup_subset
from collections import defaultdict
from itertools import groupby


def main(scope="core"):
    """验收冻结样本的均值和暴露簇处理，逐版本保存检查点。"""
    root = Path(__file__).resolve().parents[1]
    alias = "2026-11-16_主分析LAI4of5"
    params = load_config(DEFAULT_CONFIG)
    sources = {}
    names = {"event_master", "event_exposure", "route1_recovery_person_pentad", "grid_manifest", "superblock_membership"}
    if scope == "extended":
        names.add("grid_pentad")
    elif scope not in ("core", "covariates", "secondary"):
        raise ValueError("未知验收任务。")
    for module in ("M2", "M3", "M5", "M6", "M7"):
        receipt = json.loads((root / "logs" / alias / f"module_io_{module}.json").read_bytes())
        for entry in receipt["output_files"]:
            name = Path(entry["path"]).stem
            if name in names:
                path = root / entry["path"]
                if digest(path) != entry["sha256"]:
                    raise ValueError(f"输入哈希失配：{name}")
                sources[name] = entry
    data = {name: pq.read_table(root / item["path"]).to_pylist() for name, item in sources.items()
            if name != "grid_pentad"}
    blocks = {r["grid_id"]: r["block_id"] for r in data["grid_manifest"]}
    diagnostic = {r["block_id"]: r["superblock_id"] for r in data["superblock_membership"]}
    with (root / "metadata/study_area_manifest.csv").open(encoding="utf-8-sig") as f:
        bbox, = [json.loads(r["bbox"]) for r in csv.DictReader(f) if r["acceptance_status"] == "accepted"]
    assert fixed_blocks(data["grid_manifest"], bbox, params["block"]["km"], params) == blocks
    audit = dict(source_alias=alias, source_files=sources, purpose="numerical_validation_only",
        seed=params["random"]["seed"], bootstrap_n=params["block"]["bootstrap_n"],
        params_sha256=hashlib.sha256(DEFAULT_CONFIG.read_bytes()).hexdigest(),
        block_counts={str(km):len(set(fixed_blocks(data["grid_manifest"], bbox, km, params).values()))
                      for km in (params["block"]["km"], *params["sensitivity"]["block_km"].values())},
        code_sha256={f.relative_to(root).as_posix():digest(f) for f in (root / "src/M7").glob("*.py")}, results={})
    target = root / ({"extended":"metadata/local/m7_extended_validation_20261117.json",
                      "covariates":"metadata/local/m7_covariate_validation_20261117.json",
                      "secondary":"metadata/local/m7_secondary_validation_20261117.json",
                      "core":"metadata/local/m7_sensitivity_validation_20261117.json"}[scope])
    if target.exists():
        previous = json.loads(target.read_bytes())
        if any(previous[k] != audit[k] for k in audit if k != "results"):
            raise ValueError("已有检查点输入或配置不同，不允许续接。")
        audit = previous
    main_risk = data["route1_recovery_person_pentad"]
    risks = {}
    if scope == "extended":
        groups = defaultdict(list)
        for event in data["event_master"]:
            groups[event["grid_id"]].append(event)
        risks = {v:[] for v in params["sensitivity"]["followup"]}
        series = pq.read_table(root / sources["grid_pentad"]["path"], columns=[
            "product_combo", "grid_id", "support_id", "t_abs", "smp", "active_flag"],
            filters=[("grid_id", "in", sorted(groups))]).sort_by([("grid_id", "ascending"), ("t_abs", "ascending")])
        rows = (r for b in series.to_batches(max_chunksize=8192) for r in b.to_pylist())
        for grid, values in groupby(rows, key=lambda r:r["grid_id"]):
            values = list(values)
            for version, horizon in params["sensitivity"]["followup"].items():
                risks[version].extend(recovery_risk(groups[grid], values, params, horizon=horizon,
                                                   exposure_version="lai_four_of_five"))
        for version in params["route1"]["q1_censor_sensitivities"]:
            risks[version] = followup_subset(main_risk, version)
        del series
    versions = ([*params["sensitivity"]["block_km"], *risks] if scope == "extended" else
                ["year_factor", "reduced_soil_terrain"] if scope == "covariates" else
                ["q3_continuous"] if scope == "secondary" else
                ["q2_mean", "common_sample", "one_per_exposure", "inverse_exposure"])
    for version in versions:
        if version in audit["results"]:
            continue
        alternate = (fixed_blocks(data["grid_manifest"], bbox, params["sensitivity"]["block_km"][version], params)
                     if version in params["sensitivity"]["block_km"] else blocks)
        output = fit_sensitivity(version, data["event_master"], data["event_exposure"],
            risks.get(version, main_risk), alternate, diagnostic if alternate is blocks else {}, params,
            {"variant":"lai_four_of_five"}, horizon=params["sensitivity"]["followup"].get(version,params["route1"]["recovery_risk_h"]),
            report=lambda stage, detail, **counts: print(version, stage, detail, flush=True)
                if not counts or counts.get("done", 0) % 100 == 0 else None)
        audit["results"][version] = output
        atomic_write(target, json_bytes(audit), replace=True)
        print("completed", version, [(r["analysis_id"],r["n_event"],r.get("bootstrap_success"))
              for r in output["sensitivity_model_manifest"]], flush=True)


if __name__ == "__main__":
    main()
