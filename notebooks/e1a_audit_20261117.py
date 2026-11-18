"""E1a只读实数据验收，零年分母与500次抽样写metadata/local。"""
import os
os.environ["OPENBLAS_NUM_THREADS"]="1"
os.environ["OMP_NUM_THREADS"]="1"
from collections import Counter
from pathlib import Path
import json
import pyarrow as pa
import pyarrow.parquet as pq
from src.M1.scr_audit_era5land import digest
from src.M7.scr_e1a_frequency import count_grid_years,fit_frequency
from workflow.run_module import load_config,DEFAULT_CONFIG
from workflow.freeze_m0 import atomic_write,json_bytes


def main():
    """核对冻结输入，不覆盖已有验收证据或正式运行。"""
    root=Path(__file__).resolve().parents[1];alias="2026-11-16_主分析LAI4of5"
    params=load_config(DEFAULT_CONFIG);params_hash=digest(DEFAULT_CONFIG)
    code_hash=digest(root/"src/M7/scr_e1a_frequency.py")
    names={"grid_pentad","grid_mask","grid_manifest","event_master","superblock_membership"}
    sources={}
    for module in ("M2","M3","M5"):
        receipt=json.loads((root/"logs"/alias/f"module_io_{module}.json").read_bytes())
        for item in receipt["output_files"]:
            name=Path(item["path"]).stem
            if name in names:
                if digest(root/item["path"])!=item["sha256"]:raise ValueError("来源哈希不符。")
                sources[name]=item
    def read(name):return pq.read_table(root/sources[name]["path"]).to_pylist()
    blocks={r["grid_id"]:r["block_id"] for r in read("grid_manifest")}
    superblocks={r["block_id"]:r["superblock_id"] for r in read("superblock_membership")}
    rows=count_grid_years(pq.ParquetFile(root/sources["grid_pentad"]["path"]).iter_batches(columns=[
        "grid_id","year","active_flag","active_window_length_L","smp","p_mm","p95_usable"]),
        read("grid_mask"),read("event_master"),blocks,params)
    census=dict(Counter(r["exclusion_reason"] or "included" for r in rows))
    print("census",census,flush=True)
    directory=root/"metadata/local";target=directory/"e1a_grid_year_validation_20261117.parquet"
    if target.exists():raise ValueError("E1a分母验收已存在，不覆盖。")
    temporary=target.with_suffix(".tmp")
    pq.write_table(pa.Table.from_pylist(rows),temporary);temporary.replace(target)
    output,audit=fit_frequency(rows,superblocks,params,report=lambda stage,detail,**counts:
        print(stage,detail,flush=True) if counts.get("done",0)%100==0 else None)
    atomic_write(directory/"e1a_validation_20261117.json",json_bytes(dict(purpose="numerical_validation_only",
        source_alias=alias,source_files=sources,params_sha256=params_hash,params_snapshot=params,
        code_sha256=code_hash,census=census,model=output,audit=audit)))
    print("finished",audit,flush=True)


if __name__=="__main__":main()
