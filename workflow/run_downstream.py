"""编排 M3–M10，检查冻结交接并原子发布模块目录。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module route1。
输入：冻结身份、上游回执和补充输入登记。输出：模块表、回执和状态。
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .freeze_m0 import atomic_write, index_lock, json_bytes
from .run_era5land import csv_bytes, frozen_context, run_era5land, update_status


def verify_file(root, item, digest):
    """核对项目内文件及登记哈希，返回路径。"""
    path = (root / item["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or digest(path) != item["sha256"]:
        raise ValueError(f"交接文件不存在或哈希不符：{item['path']}")
    return path


def registered_inputs(root, path, digest):
    """读取附加交接登记，验证标准表和对应原始文件哈希。"""
    if not path.is_file():
        return {}, []
    content = path.read_bytes()
    evidence = json.loads(content)
    files = [{"path": path.relative_to(root).as_posix(), "sha256": sha256(content).hexdigest()}]
    datasets = {}
    for name, entry in sorted(evidence.items()):
        if entry.get("status") != "accepted" or not entry.get("sources"):
            continue
        source_paths = [verify_file(root, item, digest) for item in entry["sources"]]
        if any(not source.is_relative_to(root / "data/raw") for source in source_paths):
            raise ValueError(f"原生证据路径超出原始数据目录：{name}")
        target = verify_file(root, entry, digest)
        if not target.is_relative_to(root / "data/interim"):
            raise ValueError(f"附加交接路径超出中间数据目录：{name}")
        datasets[name] = target
        files.extend([entry, *entry["sources"]])
    return datasets, [{"path": item["path"], "sha256": item["sha256"]} for item in files]


def compute_module(module, tables, supplements, params, plan, matrix):
    """从已核验的输入计算模块表及状态。"""
    import pyarrow.parquet as pq
    from src.M3.scr_build_climatology import build_climatology
    from src.M3.scr_prepare_support import prepare_support
    from src.M4.scr_connect_regions import connect_regions
    from src.M4.scr_detect_events import detect_events
    from src.M5.scr_derive_outcomes import derive_outcomes
    from src.M5.scr_group_wet_processes import group_wet_processes
    from src.M6.scr_background_climate import background_climate
    from src.M6.scr_link_exposures import link_exposures
    from src.M7.scr_route1_summary import recovery_risk, summarize, trend_estimates
    from src.M8.scr_encode_exits import encode_exits
    from src.M9.scr_match_events import match_grid_events
    from src.M10.scr_review_results import review_events

    def read(name, columns=None):
        return pq.read_table(tables[name], columns=columns).to_pylist()

    series_keys = ["product_combo", "grid_id", "support_id", "t_abs"]

    def extra(name):
        return pq.read_table(supplements[name]).to_pylist() if name in supplements else []

    status, details = "passed", {}
    result = {}
    if module == "M3":
        required = "grid_support"
        if required not in supplements:
            return {}, "conditional_skipped", {"missing": ["MCD12Q1.061", "MCD12Q2.061"], "required_handoff": required}
        support, mask, phenology = prepare_support(json.loads(supplements[required].read_bytes()),
                                                  read("grid_manifest"), params, plan["variant"])
        climate, pentads, active = build_climatology(read("grid_pentad_base_era5land"), support,
                                                      params, plan["product_combo"])
        result.update(grid_mask=mask, grid_phenology_year=phenology, grid_climatology=climate,
                      grid_pentad=pentads, grid_active_pentad=active)
    elif module == "M4":
        result["event_master_base"], result["event_candidate_audit"] = detect_events(read("grid_pentad"), params)
        result["event_regional"], result["event_regional_member"] = connect_regions(
            result["event_master_base"], read("grid_manifest"), params)
    elif module == "M5":
        pentads = read("grid_pentad")
        values = derive_outcomes(read("event_master_base"), pentads, params)
        result.update(zip(("event_master", "event_precip", "event_branch", "event_recovery_trajectory"), values))
        result["wet_process_membership"], result["superblock_membership"] = group_wet_processes(
            values[0], values[2], pentads, read("grid_manifest"), params)
    elif module == "M6":
        daily = pq.ParquetFile(tables["grid_day_era5land"])
        climate = background_climate((batch.to_pylist() for batch in daily.iter_batches(
            columns=["grid_id", "date", "p_mm", "t2m_c"])), params)
        static = {row["grid_id"]: row for row in extra("grid_static_covariates")}
        static = {key: {**static.get(key, {}), **value} for key, value in climate.items()}
        annual = extra("vegetation_grid_year")
        result["event_exposure"], result["exposure_cluster_audit"] = link_exposures(
            read("event_master"), read("grid_pentad", [
                *series_keys, "year", "pentad", "sm_0_100_mm", "sm_deep_mm"]),
            annual, static, params)
        result["vegetation_grid_year"] = annual
        if not annual or "grid_static_covariates" not in supplements:
            status = "descriptive_only"
            details["missing"] = [name for name in ("vegetation_grid_year", "grid_static_covariates")
                                  if name not in supplements]
    elif module == "M7":
        events = read("event_master")
        result["route1_recovery_person_pentad"] = recovery_risk(events, read("grid_pentad", [*series_keys, "smp", "active_flag"]), params)
        result["q1_annual"], result["q2_annual"] = summarize(events, params)
        result["trend_estimate"] = trend_estimates(result["q1_annual"], params)
        status = "descriptive_only"
        details["pending"] = ["Q1 趋势推断", "Q2 调整对比", "Q3 模型"]
    elif module == "M8":
        blocks = {row["grid_id"]: row["block_id"] for row in read("grid_manifest")}
        person, exits, gate = encode_exits(read("event_master"), read("grid_pentad", [
            *series_keys, "smp", "p_mm", "p95_mm", "p95_usable"]), params, blocks)
        result.update(route2_person_pentad=person, route2_exit=exits)
        status, details = gate["status"], gate
    elif module == "M9":
        main = read("event_master")
        result["cross_product_event_match"] = []
        result["cross_product_match_summary"] = []
        result["spec_manifest"] = [dict(estimand=estimand, specification=variant, status="pending")
                                   for estimand, definition in matrix["estimands"].items()
                                   for variant in definition["specifications"]]
        missing = []
        for combo in params["products"]["combinations"]:
            if combo == params["products"]["main"]:
                continue
            name = f"event_master_{combo}"
            if name not in supplements:
                missing.append(combo)
                continue
            alternatives = extra(name)
            if any(row["product"] != combo for row in alternatives):
                raise ValueError(f"替代事件表的产品标识不符：{combo}")
            common_keys = {(row["grid_version"], row["support_id"]) for row in main}
            alt_keys = {(row["grid_version"], row["support_id"]) for row in alternatives}
            if len(common_keys | alt_keys) > 1:
                raise ValueError(f"事件匹配需要相同网格与空间支撑：{combo}")
            matches = match_grid_events(main, alternatives, params["robustness"]["match_tolerance"])
            n, a, b = len(matches), len(main), len(alternatives)
            result["cross_product_match_summary"].append(dict(
                product_combo=combo, n_main=a, n_alt=b, n_match=n,
                main_hit=n/a if a else None, alt_hit=n/b if b else None,
                jaccard=n/(a+b-n) if a+b-n else None))
            result["cross_product_event_match"].extend(dict(row, product_combo=combo) for row in matches)
        status = "descriptive_only"
        details["missing"] = missing
    elif module == "M10":
        events = read("event_master")
        review = review_events(events, read("grid_pentad", [*series_keys, "smp"]), params)
        result["review_event_recalc"] = review
        n_recovered = sum(row["t_e"] is not None for row in events)
        n_candidates = pq.ParquetFile(tables["event_candidate_audit"]).metadata.num_rows
        flow = [
            ("M4", "候选进入事件库", n_candidates, len(events)),
            ("M5", "有恢复终止", len(events), n_recovered),
            ("M7", "路线一条件 A", n_recovered, sum(row["route1_A_eligible"] for row in events)),
            ("M7", "条件 A 降水接续可判", sum(row["route1_A_eligible"] for row in events),
             sum(row["route1_A_eligible"] and row["F_R"] is not None for row in events)),
        ]
        result["sample_flow"] = [dict(analysis_id="route1", step_order=i, module=owner, step_name=step,
                                      n_before=before, n_after=after, n_excluded=before-after, unit="event",
                                      product=plan["product_combo"], definition_id=plan["variant"])
                                 for i, (owner, step, before, after) in enumerate(flow, 1)]
        details.update(event_count=len(events), reviewed=len(review),
                       review_target=params["review"]["minimum_events"],
                       review_target_met=len(review) >= params["review"]["minimum_events"],
                       pending=["独立事件识别复算", "模型复核与论文图表"])
        status = "descriptive_only" if all(row["passed"] for row in review) else "failed"
    return result, status, details


def write_table(path, rows, definition):
    """依登记字段顺序写表，校验主键，空表保留字段。"""
    import pyarrow as pa
    import pyarrow.parquet as pq

    columns = definition["columns"]
    primary = definition.get("primary_key", [])
    if primary:
        keys = [tuple(row.get(name) for name in primary) for row in rows]
        if any(None in key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError(f"主键缺失或重复：{path.stem}")
    table = pa.table({column: [row.get(column) for row in rows] for column in columns})
    pq.write_table(table, path)


def run_downstream(root, plan, config_path, params, load_config, progress):
    """串联既有 M1/M2 和下游模块，支持冻结交接复用。"""
    from src.M1.scr_audit_era5land import digest

    if plan["product_combo"] != params["products"]["main"] or plan["variant"] not in {"main", "fixed_season"}:
        raise ValueError("当前下游编排仅接受 ERA5-Land 与已接入的主规范或固定季节。")
    upstream = run_era5land(root, {**plan, "modules": ["M0", "M1", "M2"]},
                            config_path, params, load_config, progress)
    statuses = upstream["module_status"]
    if statuses.get("M2") != "passed":
        return {**upstream, **plan, "run_id": upstream["run_id"], "module_status": statuses}
    record, identity, output, logs, _ = frozen_context(root, plan, config_path, params, digest)
    schema = load_config(root / "config/schema_registry.yaml")["tables"]
    matrix = load_config(root / "config/specification_matrix.yaml")
    frozen = (root / params["output"]["frozen"]).resolve()
    if frozen != root / "data/frozen":
        raise ValueError("冻结路径超出登记范围。")
    destination = frozen / "downstream" / plan["run_alias"]
    registration = root / params["downstream"]["supplement_manifest"]
    tables = {}

    def item(path):
        return {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}

    def index_outputs(receipt):
        for entry in receipt["output_files"]:
            path = verify_file(root, entry, digest)
            if path.suffix == ".parquet":
                tables[path.stem] = path

    dag = load_config(root / "workflow/dag.yaml")["modules"]
    with index_lock(logs / ".downstream.lock"):
        supplements, evidence = registered_inputs(root, registration, digest)
        m2_path = logs / "module_io_M2.json"
        index_outputs(json.loads(m2_path.read_bytes()))
        base_inputs = [item(m2_path), *evidence]
        for module in plan["modules"][3:]:
            progress(module, "核对交接及模块状态", None)
            stage_dir = destination / module
            receipt_path = stage_dir / "module_io.json"
            blocked = [key for key in dag[module]["requires"]
                       if statuses.get(key) not in ("passed", "descriptive_only", "exited")]
            if blocked:
                statuses[module] = "conditional_skipped"
                update_status(logs, module, statuses[module])
                continue
            inputs = [*base_inputs, *(item(destination / key / "module_io.json")
                                      for key in dag[module]["requires"] if key not in ("M0", "M1", "M2"))]
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_bytes())
                if receipt["run_id"] != record["run_id"] or receipt["input_files"] != inputs:
                    raise ValueError(f"{module} 输入已变化，请使用新别名。")
                index_outputs(receipt)
            else:
                if stage_dir.exists():
                    raise ValueError(f"{module} 目录已存在且缺少冻结回执。")
                destination.mkdir(parents=True, exist_ok=True)
                try:
                    result, status, details = compute_module(module, tables, supplements, params, plan, matrix)
                    with TemporaryDirectory(dir=destination, prefix=".stage-") as tmp:
                        stage = Path(tmp) / module
                        stage.mkdir()
                        for name, rows in result.items():
                            definition = schema["event_master" if name == "event_master_base" else name]
                            write_table(stage / f"{name}.parquet", rows, definition)
                        if module == "M8":
                            atomic_write(stage / "route2_gate.json", json_bytes(details))
                        if "sample_flow" in result:
                            atomic_write(stage / "sample_flow.csv",
                                         csv_bytes(schema["sample_flow"]["columns"], result["sample_flow"]))
                        if module == "M10" and status != "failed":
                            from src.M10.scr_plot_figures import export_figures
                            import pyarrow.parquet as pq

                            figure_sources = {
                                "sample_flow": result["sample_flow"],
                                "event_master": pq.read_table(tables["event_master"], columns=[
                                    "route1_A_eligible", "RT", "delta_SMP", "RR",
                                    "F_R", "F_R_subtype", "Lag_FR",
                                ]).to_pylist(),
                                "cross_product_match_summary": pq.read_table(
                                    tables["cross_product_match_summary"]).to_pylist(),
                            }
                            figures = export_figures(stage / "figures", figure_sources, {
                                "run_id": record["run_id"],
                                "product_combo": plan["product_combo"], "variant": plan["variant"],
                                "study_years": [params["time"]["year_start"], params["time"]["year_end"]],
                            })
                            atomic_write(stage / "figures/figure_manifest.json", json_bytes(figures))
                        atomic_write(stage / "run.json", json_bytes({**identity, "module": module, "status": status}))
                        outputs = [{"path": (stage_dir / path.relative_to(stage)).relative_to(root).as_posix(),
                                    "sha256": digest(path)}
                                   for path in sorted(stage.rglob("*")) if path.is_file()]
                        for entry in inputs:
                            verify_file(root, entry, digest)
                        receipt = dict(run_id=record["run_id"], module_id=module, status=status, details=details,
                                       input_files=inputs, output_files=outputs)
                        atomic_write(stage / receipt_path.name, json_bytes(receipt))
                        stage.rename(stage_dir)
                    index_outputs(receipt)
                except Exception:
                    update_status(logs, module, "failed")
                    raise
            statuses[module] = receipt["status"]
            update_status(logs, module, receipt["status"])
            stamp = datetime.now(timezone.utc).isoformat()
            event = dict(time=stamp, level="INFO", message=f"{module} 交接状态已登记", status=receipt["status"])
            atomic_write(logs / module / f"{stamp.replace(':', '-')}.jsonl", json_bytes(event))
            if module == "M10" and receipt["status"] != "failed":
                flow = stage_dir / "sample_flow.csv"
                atomic_write(output / "tables/sample_flow.csv", flow.read_bytes())
                figure_dir = stage_dir / "figures"
                for path in sorted(figure_dir.iterdir()):
                    atomic_write(output / "figures" / path.name, path.read_bytes())
                atomic_write(output / "result_manifest.json", json_bytes({
                    "run_id": record["run_id"], "status": receipt["status"],
                    "figure_manifest": item(output / "figures/figure_manifest.json"),
                    "module_receipts": [item(path) for path in sorted(destination.glob("M*/module_io.json"))
                                        if path.parent.name in plan["modules"] and path.parent.name != "M8"],
                }))
    return {**plan, "run_id": record["run_id"], "module_status": statuses, "downstream": str(destination), "m1_reports": upstream["m1_reports"]}
