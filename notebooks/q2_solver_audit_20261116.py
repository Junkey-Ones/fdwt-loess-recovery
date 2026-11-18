"""Q2求解器只读调试验收：冻结样本、原种子500次、证书与旧算法对照。
本脚本不发布正式M7结果，仅写metadata/local的数值验收证据。
"""
import os
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
import ast
import hashlib
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from time import monotonic
import numpy as np
import pyarrow.parquet as pq
from src.M7.scr_fit_median import fit_weighted_median
from src.M7.scr_fit_route1_models import design_matrix
from workflow.run_module import load_config, DEFAULT_CONFIG


def main():
    """仅对冻结输入执行数值调试，不改变正式结果与参数。"""
    root = Path(__file__).resolve().parents[1]
    alias = "2026-11-16_主分析LAI4of5"
    params = load_config(DEFAULT_CONFIG)
    frozen = json.loads((root / "outputs" / alias / "protocol_freeze.json").read_text(encoding="utf-8"))
    assert hashlib.sha256((root / "config/params.yaml").read_bytes()).hexdigest() == frozen["input_sha256"]["config/params.yaml"]
    source_files = []
    for module in ("M5", "M6"):
        receipt = json.loads((root / "logs" / alias / f"module_io_{module}.json").read_text(encoding="utf-8"))
        for entry in receipt["output_files"]:
            if Path(entry["path"]).name in ("event_master.parquet", "event_exposure.parquet"):
                assert hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
                source_files.append(entry)
    tables = {Path(f["path"]).stem: pq.read_table(root / f["path"]).to_pylist() for f in source_files}
    exposures = {r["episode_id"]: r for r in tables["event_exposure"]}
    rows = [{**r, **exposures[r["episode_id"]]} for r in tables["event_master"]]
    core = params["covariates"]["core"]
    rows = [dict(r, fr_pre_sync=int(r["F_R"])) for r in rows
            if r["route1_FR_eligible"] and r["F_R"] is not None
            and (not r["F_R"] or r["F_R_subtype"] in ("pre", "sync"))
            and all(r.get(k) is not None and (bool(r[k]) if k == "land_cover" else np.isfinite(r[k])) for k in core)
            and all(r[k] is not None and np.isfinite(r[k]) for k in ("RR", "delta_SMP"))]
    _, x, _ = design_matrix(rows, ["fr_pre_sync"], core)
    data = {"x": x, "rr": np.array([r["RR"] for r in rows]),
            "delta": np.array([r["delta_SMP"] for r in rows]), "grids": [r["grid_id"] for r in rows]}
    receipt = json.loads((root / "logs" / alias / "module_io_M2.json").read_text(encoding="utf-8"))
    grid_path = next(r["path"] for r in receipt["output_files"] if r["path"].endswith("/grid_manifest.parquet"))
    grid = pq.read_table(root / grid_path).to_pylist()
    mapping = {r["grid_id"]: r["block_id"] for r in grid}
    blocks = [mapping[g] for g in data["grids"]]
    keys = sorted(set(blocks))
    codes = np.array([keys.index(b) for b in blocks])
    rng = np.random.default_rng(params["random"]["seed"])
    weights = [np.bincount(rng.integers(len(keys), size=len(keys)), minlength=len(keys))[codes]
               for _ in range(params["block"]["bootstrap_n"])]
    tree = ast.parse(frozen["code_snapshot"]["src/M7/scr_fit_route1_models.py"])
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fit_coefficients")
    namespace = {"np": np}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "frozen_solver", "exec"), namespace)
    old_fit = namespace["fit_coefficients"]
    result = {"source_alias": alias, "source_run_id": frozen["run_id"], "n_event": len(codes),
              "n_block": len(keys), "seed": params["random"]["seed"], "source_files": source_files,
              "purpose": "numerical_validation_only", "models": {}}
    start = monotonic()
    for outcome in ("rr", "delta"):
        x, y = data["x"], data[outcome]
        beta, status, audit = fit_weighted_median(x, y, np.ones(len(y)))
        old_beta, old_status = old_fit(x, y, np.ones(len(y)), "median")
        rows = []
        def solve(item):
            i, w = item
            b, s, d = fit_weighted_median(x, y, w)
            return {"draw": i, "status": s, "contrast": float(b[1]) if b is not None else None, **d}
        # 技术并发仅用于只读数值验收，不改变抽样顺序或权重。
        with ThreadPoolExecutor(max_workers=2) as pool:
            for row in pool.map(solve, enumerate(weights)):
                rows.append(row)
                if len(rows) % 25 == 0:
                    print(outcome, len(rows), "success", sum(r["status"] == "fitted" for r in rows),
                          "seconds", round(monotonic()-start), flush=True)
        # 原算法逐次找出首个失败，证明修复覆盖了同一个失败抽样。
        failed_example = None
        for i, w in enumerate(weights):
            b, s = old_fit(x, y, w, "median")
            if b is None:
                failed_example = {"draw": i, "old_status": s, "new": rows[i]}
                break
        result["models"][outcome] = {"main_status": status, "main_contrast": float(beta[1]),
             "main_certificate": audit, "old_main_status": old_status,
             "old_main_contrast": float(old_beta[1]) if old_beta is not None else None,
             "old_main_objective": float(np.abs(y-x @ old_beta).sum()) if old_beta is not None else None,
             "successful_draws": sum(r["status"] == "fitted" for r in rows),
             "old_failure_example": failed_example, "draws": rows}
        target = root / "metadata/local/q2_solver_validation_20261116.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
    print("COMPLETE", round(monotonic()-start), flush=True)


if __name__ == "__main__":
    main()
