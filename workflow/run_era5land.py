"""脚本名：run_era5land.py（编排层 · M1/M2 交接）
功能简介：核验冻结身份，调度 ERA5-Land 验收及预处理。
作者：Codex
版本：v0.1.0
读取数据：M0 冻结回执、运行索引、统一配置和本地来源登记。
生成数据：M1 报告、M2 中间表和哈希回执。
其他文件：运行日志和模块状态。
运行示例：python -m workflow.run_module M2 --run-alias 2026-11-10_主分析
退出码：由统一入口定义。
"""
import csv
from datetime import date, datetime, timezone
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import monotonic
from uuid import uuid4

from .freeze_m0 import atomic_write, index_lock, json_bytes
from .progress import emit


def csv_bytes(columns, rows):
    """按登记列序编码 CSV，保留空表表头。"""
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def frozen_context(root, plan, config_path, params, digest):
    """核验同别名 M0 回执、冻结输入、工作树和运行身份。"""
    alias = plan["run_alias"]
    output, logs = ((root / params["output"][key] / alias).resolve() for key in ("outputs", "logs"))
    if not output.is_relative_to(root / "outputs") or not logs.is_relative_to(root / "logs"):
        raise ValueError("运行目录超出登记范围。")
    with (root / "metadata/run_index.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = [row for row in csv.DictReader(source) if row["run_alias"] == alias]
    if len(rows) != 1 or not (logs / "module_io_M0.json").is_file():
        raise ValueError("请先使用同一别名正式冻结 M0。")
    record_path = output / "protocol_freeze.json"
    record = json.loads(record_path.read_bytes())
    receipt = json.loads((logs / "module_io_M0.json").read_bytes())
    identity = json.loads((output / "run.json").read_bytes())
    keys = ("run_id", "params_hash", "code_hash")
    if (receipt["status"] != "passed" or rows[0]["run_id"] != record["run_id"]
            or any(receipt[key] != record[key] or identity[key] != record[key] for key in keys)
            or plan["run_id"] not in (None, record["run_id"])
            or any(plan[key] != record[key] for key in ("product_combo", "variant"))
            or receipt["output_files"] != [{"path": record_path.relative_to(root).as_posix(),
                                           "sha256": digest(record_path)}]):
        raise ValueError("M0 冻结身份与请求不匹配。")
    config_key = Path(config_path).resolve().relative_to(root).as_posix()
    if config_key not in record["input_sha256"]:
        raise ValueError("所选配置没有登记于 M0 冻结。")
    for path, expected in record["input_sha256"].items():
        if digest(root / path) != expected:
            raise ValueError(f"冻结输入已变化，请使用新别名：{path}")
    files = {path.relative_to(root).as_posix(): digest(path) for directory in ("src", "workflow")
             for path in (root / directory).rglob("*.py")}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if files != record["code_files"] or commit != record["git_commit"]:
        raise ValueError("代码身份已变化，请使用新别名重新冻结。")
    with (root / "metadata/study_area_manifest.csv").open(encoding="utf-8-sig", newline="") as source:
        accepted = [row for row in csv.DictReader(source) if row["acceptance_status"] == "accepted"]
    if len(accepted) != 1:
        raise ValueError("当前实现需要唯一放行的矩形研究区。")
    boundary = accepted[0]
    geometry = json.loads((root / boundary["file_name"]).read_bytes())
    bbox = json.loads(boundary["bbox"])
    west, south, east, north = bbox
    expected = {(west, south), (west, north), (east, south), (east, north)}
    ring = geometry["geometry"]["coordinates"][0]
    if len(ring) != 5 or set(map(tuple, ring)) != expected:
        raise ValueError("研究区几何与登记矩形不符。")
    return record, identity, output, logs, bbox


def update_status(logs, module, status):
    """更新当前模块状态。"""
    path = logs / "module_status.csv"
    rows = list(csv.DictReader(StringIO(path.read_text(encoding="utf-8-sig"))))
    for row in rows:
        if row["module_id"] == module:
            row["status"] = status
    atomic_write(path, csv_bytes(("module_id", "status"), rows), replace=True)


def run_era5land(root, plan, config_path, params, load_config, progress):
    """执行 M1，放行后可在同一冻结身份下执行 M2。"""
    from src.M1.scr_audit_era5land import audit_era5land, digest, era5land_years
    from src.M2.scr_prepare_era5land import prepare_era5land

    if plan["product_combo"] != "era5land__era5land" or plan["variant"] not in {"main", "fixed_season"}:
        raise ValueError("当前 M1/M2 只接入 ERA5-Land 及已实现的主规范和固定季节。")
    if not plan["resume"]:
        raise ValueError("M1/M2 需要续接正式冻结的 M0。请先单独执行 M0 正式冻结，再用同一别名运行。")
    emit(progress, "M0", "核验冻结身份")
    record, identity, output, logs, bbox = frozen_context(root, plan, config_path, params, digest)
    emit(progress, "M0", "冻结身份已核验", state="reused")
    try:
        import netCDF4
        import numpy
        if plan["modules"][-1] == "M2":
            import pyarrow
    except ImportError as error:
        raise ValueError("请先安装 environment.yml 中登记的科学依赖。") from error
    schema = load_config(root / "config/schema_registry.yaml")["tables"]
    evidence_path = root / params["native_era5land"]["evidence"]
    evidence_bytes = evidence_path.read_bytes() if evidence_path.is_file() else None
    evidence = load_config(evidence_path, content=evidence_bytes) if evidence_bytes is not None else {}
    evidence_hash = sha256(evidence_bytes).hexdigest() if evidence_bytes is not None else None
    base = {key: record[key] for key in ("run_id", "params_hash", "code_hash")}
    base["random_seed_id"] = params["random"]["seed_id"]

    def file_record(path):
        return {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}

    def publish(module, receipt, started):
        now = datetime.now(timezone.utc)
        event = {"time": now.isoformat(), "level": "INFO", "message": f"{module} 已生成审计回执",
                 "stdout": receipt, "stderr": [], "runtime": plan.get("runtime"),
                 "elapsed_seconds": monotonic() - started}
        stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
        atomic_write(logs / module / f"{module}_{stamp}_{uuid4().hex}.jsonl",
                     (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
        atomic_write(logs / f"module_io_{module}.json", json_bytes(receipt))
        update_status(logs, module, receipt["status"])

    def read_receipt(module):
        path = logs / f"module_io_{module}.json"
        if not path.is_file():
            return None
        receipt = json.loads(path.read_bytes())
        if any(receipt[key] != value for key, value in base.items()):
            raise ValueError(f"{module} 回执身份不符。")
        for item in receipt["output_files"]:
            if digest(root / item["path"]) != item["sha256"]:
                raise ValueError(f"{module} 产物哈希不符：{item['path']}")
        update_status(logs, module, receipt["status"])
        return receipt

    with index_lock(logs / ".m1_m2.lock"):
        emit(progress, "M1", "核对验收回执")
        m1 = read_receipt("M1")
        reused_m1 = m1 is not None
        if m1 is not None and m1["evidence_sha256"] != evidence_hash:
            raise ValueError("来源登记已变化，请使用新别名重新验收。")
        if m1 is None:
            started = monotonic()
            emit(progress, "M1", "原始数据验收")
            files, checks, mappings, missing = audit_era5land(root, params, bbox, evidence, progress,
                                                            plan.get("runtime"))
            status = "passed" if not missing else (
                "failed" if any(row["audit_status"] == "failed" for row in files) else "exited")
            coverage = []
            first, last = era5land_years(params)
            for year in range(first, last + 1):
                annual = [row for row in files if row["time_start"].startswith(str(year))]
                annual_missing = [row["period"] for row in missing if row["period"].startswith(str(year))]
                coverage.append({"product_code": "era5land", "year": year,
                    "n_source_files_expected": len(annual),
                    "n_source_files_received": sum("sha256" in row for row in annual),
                    "n_days_expected": (date(year + 1, 1, 1) - date(year, 1, 1)).days,
                    "n_pentads_expected": params["time"]["pentads_per_year"],
                    "missing_periods": ";".join(sorted(set(annual_missing))),
                    "coverage_status": "pending" if annual_missing else "native_time_checked"})
            for name in ("mcd12q1", "mcd12q2", "mcd15a3h", "soilgrids", "nasadem", "gldas21",
                         "chirps20", "mod13q1", "station", "circulation"):
                coverage.append({"product_code": name, "coverage_status": "conditional_skipped"})
                missing.append({"product_code": name, "reason": "该产品未接入本次 ERA5-Land 验收。"})
            accepted = sum(row["audit_status"] == "accepted" for row in files)
            reports = {"source_file_manifest": files, "source_variable_map": mappings,
                       "sop_native_acceptance": checks, "m1_missing_files": missing,
                       "sop_product_coverage": coverage,
                       "m1_data_coverage": [{"product_code": "era5land", "n_expected": len(files),
                                             "n_received": sum("sha256" in row for row in files),
                                             "n_accepted": accepted, "coverage_status": status}],
                       "m1_sample_flow": [{"stage": "原生文件验收", "n_before": len(files),
                                            "n_after": accepted, "reason": "文件缺失或验收待完成"}]}
            emit(progress, "M1", "写入验收报告")
            output_files = []
            for name, rows in reports.items():
                path = output / "reports" / f"{name}.csv"
                atomic_write(path, csv_bytes(schema[name]["columns"], rows))
                output_files.append(file_record(path))
            m1 = {**base, "module_id": "M1", "status": status, "evidence_sha256": evidence_hash,
                  "input_files": [{"path": row["file_path"], "sha256": row["sha256"]}
                                  for row in files if "sha256" in row], "output_files": output_files}
            emit(progress, "M1", "发布验收回执")
            publish("M1", m1, started)
        emit(progress, "M1", "验收结束",
             state="reused" if reused_m1 and m1["status"] == "passed" else m1["status"])

        result = {**plan, "run_id": record["run_id"], "module_status": {"M1": m1["status"]},
                  "m1_reports": str(output / "reports")}
        if plan["modules"][-1] == "M1" or m1["status"] != "passed":
            return result

        def verify_raw(stage):
            paths = [(root / item["path"], item["sha256"]) for item in m1["input_files"]]
            total = sum(path.stat().st_size for path, _ in paths)
            done = 0
            emit(progress, "M2", stage, total=total, unit="字节")
            for path, checksum in paths:
                def advance(size):
                    nonlocal done
                    done += size
                    emit(progress, "M2", stage, path.name, done=done, total=total, unit="字节")

                if digest(path, advance) != checksum:
                    raise ValueError(f"M1 原始文件哈希已变化：{path.name}")

        started = monotonic()
        verify_raw("核验原始输入")
        emit(progress, "M2", "核对预处理回执")
        m2 = read_receipt("M2")
        reused_m2 = m2 is not None
        destination = (root / params["output"]["interim"] / "era5land_base" / plan["run_alias"]).resolve()
        if not destination.is_relative_to(root / "data/interim"):
            raise ValueError("M2 路径超出中间数据目录。")
        if m2 is None:
            m1_link = file_record(logs / "module_io_M1.json")
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                try:
                    with TemporaryDirectory(dir=destination.parent, prefix=".m2-") as temporary:
                        stage = Path(temporary) / "stage"
                        stage.mkdir()
                        emit(progress, "M2", "日候归并")
                        prepare_era5land(root, stage, params, bbox, schema, progress, plan.get("runtime"))
                        verify_raw("复核原始输入")
                        emit(progress, "M2", "写入预处理清单")
                        atomic_write(stage / "run.json", json_bytes({**identity, "module": "M2",
                                                                    "status": "passed", "upstream": m1_link,
                                                                    "table_sha256": {path.name: digest(path)
                                                                                        for path in stage.glob("*.parquet")}}))
                        stage.rename(destination)
                except Exception:
                    update_status(logs, "M2", "failed")
                    raise
            emit(progress, "M2", "校验预处理交接")
            saved = json.loads((destination / "run.json").read_bytes())
            expected = {"grid_manifest.parquet", "time_pentad_calendar.parquet", "run.json",
                        "grid_day_era5land.parquet", "grid_pentad_base_era5land.parquet"}
            if (saved.get("upstream") != m1_link or saved.get("run_id") != record["run_id"]
                    or {path.name for path in destination.iterdir()} != expected
                    or saved.get("table_sha256") != {path.name: digest(path)
                                                       for path in destination.glob("*.parquet")}):
                raise ValueError("已有 M2 目录与登记产物不匹配。")
            m2 = {**base, "module_id": "M2", "status": "passed", "input_files": [m1_link],
                  "output_files": [file_record(path) for path in sorted(destination.iterdir())]}
            emit(progress, "M2", "发布预处理回执")
            publish("M2", m2, started)
        result["module_status"]["M2"] = m2["status"]
        emit(progress, "M2", "预处理结束", state="reused" if reused_m2 else m2["status"])
        return {**result, "m2_interim": str(destination)}
