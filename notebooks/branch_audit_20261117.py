"""FZ/DFAI只读实数据验收，不改正式结果。"""
import os
os.environ["OPENBLAS_NUM_THREADS"]="1"
os.environ["OMP_NUM_THREADS"]="1"
from pathlib import Path
import json
import pyarrow.parquet as pq
from src.M1.scr_audit_era5land import digest
from src.M7.scr_branch_supplements import branch_supplements
from workflow.run_module import load_config,DEFAULT_CONFIG
from workflow.freeze_m0 import atomic_write,json_bytes
from workflow.run_downstream import arrow_table


def main():
    """固定来源哈希和配置快照，按原种子500次核验补充分支。"""
    root=Path(__file__).resolve().parents[1];alias="2026-11-16_主分析LAI4of5"
    params=load_config(DEFAULT_CONFIG);params_hash=digest(DEFAULT_CONFIG)
    code={p.relative_to(root).as_posix():digest(p) for p in (root/"src/M7").glob("*.py")}
    needed={"event_master","event_exposure","event_branch","event_recovery_trajectory","grid_manifest","superblock_membership"}
    source={}
    for module in ("M2","M5","M6"):
        receipt=json.loads((root/"logs"/alias/f"module_io_{module}.json").read_bytes())
        for item in receipt["output_files"]:
            name=Path(item["path"]).stem
            if name in needed:
                if digest(root/item["path"])!=item["sha256"]:raise ValueError("冻结输入哈希失配。")
                source[name]=item
    def read(name,columns=None):return pq.read_table(root/source[name]["path"],columns=columns).to_pylist()
    output,audit=branch_supplements(read("event_master"),read("event_exposure"),read("event_branch"),
        read("event_recovery_trajectory",["episode_id","t_abs","active_flag"]),
        {r["grid_id"]:r["block_id"] for r in read("grid_manifest")},
        {r["block_id"]:r["superblock_id"] for r in read("superblock_membership")},params,{"variant":"lai_four_of_five"},
        report=lambda stage,detail,**counts: print(stage,detail,flush=True) if counts.get("done",0)%100==0 else None)
    schema=load_config(DEFAULT_CONFIG.parent/"schema_registry.yaml")["tables"]
    for name,rows in output.items():arrow_table(name,rows,schema[name])
    atomic_write(root/"metadata/local/branch_validation_20261117.json",json_bytes(dict(purpose="numerical_validation_only",
        source_alias=alias,source_files=source,params_sha256=params_hash,params_snapshot=params,code_sha256=code,
        schema_validation="passed",audit=audit,results=output)))
    print("finished",audit,flush=True)


if __name__=="__main__":main()
