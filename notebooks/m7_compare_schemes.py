"""只读核对严格与修订方案的共同暴露以及不依赖LAI的主分析结果。"""
import argparse
import json
from pathlib import Path
from collections import Counter
import pyarrow.parquet as pq
from workflow.run_module import ROOT, validate_alias


def table(alias, module, name):
    """按实际运行回执定位原生或只读继承的表。"""
    receipt = json.loads((ROOT/"logs"/alias/f"module_io_{module}.json").read_bytes())
    path, = [ROOT/item["path"] for item in receipt["output_files"] if Path(item["path"]).name == name+".parquet"]
    return pq.read_table(path).to_pylist()


def compare(strict, relaxed):
    """核验方案身份、完整事件包含关系与逐键数值。"""
    for alias, variant in ((strict,"main"),(relaxed,"lai_four_of_five")):
        validate_alias(alias)
        freeze = json.loads((ROOT/"outputs"/alias/"protocol_freeze.json").read_bytes())
        if freeze["variant"] != variant:
            raise ValueError(f"方案身份不符：{alias}")
    columns = ["LAI_base","LAI_trend","deep_SM_pre4_percentile"]
    samples = []
    for alias in (strict, relaxed):
        rows = table(alias,"M6","event_exposure")
        sample = {r["episode_id"]: tuple(r[c] for c in columns) for r in rows if r["exposure_complete_I"]}
        if len(sample) != sum(bool(r["exposure_complete_I"]) for r in rows):
            raise ValueError("重复完整事件")
        samples.append(sample)
    shared = samples[0]
    if any(samples[1].get(key) != value for key, value in shared.items()):
        raise ValueError("共同事件缺失或暴露不一致")
    for name in ("q1_annual","q1_recovery_risk","q1_recovery_risk_sensitivity","q1_curve_uncertainty",
                 "q1_recovery_distribution","q1_censor_audit","trend_estimate","q2_annual","q2_lag_result",
                 "q2_fr_spatial","model_result","route1_model_uncertainty"):
        frames = []
        for alias in (strict,relaxed):
            rows = table(alias,"M7",name)
            comparable = [{k:v for k,v in r.items() if k not in ("run_id","exposure_version")}
                          for r in rows if "analysis_id" not in r or r["analysis_id"].startswith("q2_")
                          or r["analysis_id"].endswith("_D")]
            frames.append(Counter(json.dumps(r,sort_keys=True) for r in comparable))
        if frames[0] != frames[1]:
            raise ValueError(f"两方案结果不一致：{name}")
    print(f"两方案核对通过，共有完整事件 {len(shared)} 条。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("strict")
    parser.add_argument("relaxed")
    args = parser.parse_args()
    compare(args.strict,args.relaxed)

