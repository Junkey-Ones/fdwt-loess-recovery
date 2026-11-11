"""编排 M3–M10，检查冻结交接并原子发布模块目录。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module route1。
输入：冻结身份、上游回执和补充输入登记。输出：模块表、回执和状态。
"""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from .freeze_m0 import atomic_write, index_lock, json_bytes
from .progress import emit
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


def compute_module(module, tables, supplements, params, plan, matrix, stage=None, schema=None, progress=None):
    """从已核验的输入计算模块表及状态。"""
    import pyarrow.parquet as pq
    from src.M3.scr_build_climatology import build_climatology
    from src.M3.scr_prepare_support import prepare_support
    from src.M4.scr_connect_regions import connect_regions
    from src.M4.scr_detect_events import detect_events
    from src.M5.scr_derive_outcomes import derive_outcomes
    from src.M5.scr_group_wet_processes import assign_wet_processes, build_superblocks
    from src.M6.scr_background_climate import background_climate
    from src.M6.scr_link_exposures import link_exposures
    from src.M7.scr_route1_summary import recovery_risk, summarize, summarize_lags, trend_estimates
    from src.M7.scr_fit_recovery_risk import recovery_time_baseline
    from src.M8.scr_encode_exits import encode_exits
    from src.M8.scr_describe_exits import cumulative_incidence, sample_audit
    from src.M8.scr_fit_cause_specific import fit_cause_specific
    from src.M9.scr_match_events import match_grid_events
    from src.M10.scr_review_results import review_events
    from src.M10.scr_audit_handoffs import review_handoffs, summarize_missing

    def read(name, columns=None, *, events=None):
        if events is not None and not events:
            return []
        filters = None if events is None else [("grid_id", "in", sorted({row["grid_id"] for row in events}))]
        return pq.read_table(tables[name], columns=columns, filters=filters).to_pylist()

    series_keys = ["product_combo", "grid_id", "support_id", "t_abs"]

    def ordered_pentads(columns):
        series = pq.read_table(tables["grid_pentad"], columns=columns)
        series = series.sort_by([(key, "ascending") for key in series_keys])
        return (row for batch in series.to_batches(max_chunksize=8192) for row in batch.to_pylist())


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
        result.update(grid_mask=mask, grid_phenology_year=phenology)
        if stage is None:
            climate, pentads, active = build_climatology(read("grid_pentad_base_era5land"), support,
                                                         params, plan["product_combo"])
            result.update(grid_climatology=climate, grid_pentad=pentads, grid_active_pentad=active)
        else:
            write_climatology(stage, tables["grid_pentad_base_era5land"], support, params,
                              plan["product_combo"], schema, progress)
    elif module == "M4":
        columns = [*series_keys, "smp", "year", "pentad", "active_flag", "grid_version",
                   "soil_product", "precip_product", "phenology_mode", "phenology_fallback",
                   "active_window_length_L", "land_cover"]
        result["event_master_base"], result["event_candidate_audit"] = detect_events(
            ordered_pentads(columns), params, ordered=True)
        result["event_regional"], result["event_regional_member"] = connect_regions(
            result["event_master_base"], read("grid_manifest"), params)
    elif module == "M5":
        from collections import defaultdict
        from itertools import groupby

        columns = [*series_keys, "year", "pentad", "smp", "active_flag", "qc_status",
                   "p_mm", "p95_mm", "p95_usable", "w"]
        event_groups = defaultdict(list)
        for event in read("event_master_base"):
            event_groups[event["product"], event["grid_id"], event["support_id"]].append(event)
        names = ("event_master", "event_precip", "event_branch", "event_recovery_trajectory")
        result.update((name, []) for name in (*names, "wet_process_membership"))
        groups = groupby(ordered_pentads(columns), key=lambda row: tuple(row[k] for k in series_keys[:3]))
        for index, (key, group) in enumerate(groups, 1):
            pentads = list(group)
            values = derive_outcomes(event_groups.pop(key, ()), pentads, params)
            for name, rows in zip(names, values):
                result[name].extend(rows)
            result["wet_process_membership"].extend(assign_wet_processes(values[0], values[2], pentads, params))
            emit(progress, "M5", "派生格点结局", done=index, unit="格点")
        if event_groups:
            raise ValueError("部分事件找不到对应的完整格点候序列。")
        result["superblock_membership"] = build_superblocks(result["event_master"], read("grid_manifest"))
    elif module == "M6":
        daily = pq.ParquetFile(tables["grid_day_era5land"])
        def climate_batches():
            done = 0
            total = daily.metadata.num_rows
            for batch in daily.iter_batches(columns=["grid_id", "date", "p_mm", "t2m_c"]):
                yield batch
                done += batch.num_rows
                emit(progress, "M6", "汇总背景气候", done=done, total=total, unit="记录")

        climate = background_climate(climate_batches(), params)
        emit(progress, "M6", "连接事件前暴露")
        static = {row["grid_id"]: row for row in extra("grid_static_covariates")}
        static = {key: {**static.get(key, {}), **value} for key, value in climate.items()}
        annual = extra("vegetation_grid_year")
        events = read("event_master")
        result["event_exposure"], result["exposure_cluster_audit"] = link_exposures(
            events, read("grid_pentad", [*series_keys, "year", "pentad", "sm_0_100_mm", "sm_deep_mm"], events=events),
            annual, static, params)
        result["vegetation_grid_year"] = annual
        if not annual or "grid_static_covariates" not in supplements:
            status = "descriptive_only"
            details["missing"] = [name for name in ("vegetation_grid_year", "grid_static_covariates")
                                  if name not in supplements]
    elif module == "M7":
        events = read("event_master")
        risk_series = read("grid_pentad", [*series_keys, "smp", "active_flag"], events=events)
        blocks = {row["grid_id"]: row["block_id"] for row in read("grid_manifest")}
        settings = params["route1"]
        risk = recovery_risk(events, risk_series, params)
        result["route1_recovery_person_pentad"] = risk
        result["q1_recovery_risk"], details["q1_recovery_risk"] = recovery_time_baseline(
            risk, events, blocks, settings["recovery_risk_h"], settings["recovery_time_df"], params["infer"])
        result["q1_recovery_risk_sensitivity"] = []
        details["q1_recovery_risk_sensitivity"] = {}
        for version, horizon in params["sensitivity"]["followup"].items():
            curve, support = recovery_time_baseline(
                recovery_risk(events, risk_series, params, horizon=horizon), events, blocks,
                horizon, settings["recovery_time_df"], params["infer"])
            result["q1_recovery_risk_sensitivity"].extend(
                dict(row, version=version, H=horizon) for row in curve)
            details["q1_recovery_risk_sensitivity"][version] = support
        result["q1_annual"], result["q2_annual"] = summarize(events, params)
        result["q2_lag_result"] = summarize_lags(events)
        result["trend_estimate"] = trend_estimates(result["q1_annual"], params)
        result["trend_estimate_sensitivity"] = [
            dict(row, min_valid_years=minimum)
            for minimum in params["trend"]["sensitivity_min_valid_years"]
            for row in trend_estimates(result["q1_annual"], params, minimum_years=minimum)
        ]
        status = "descriptive_only"
        details["q1_trend_status"] = {row["metric"]: row["status"] for row in result["trend_estimate"]}
        details["pending"] = ["Q1 恢复风险区间和敏感性、趋势伴随诊断", "Q2 调整对比", "Q3 模型"]
    elif module == "M8":
        blocks = {row["grid_id"]: row["block_id"] for row in read("grid_manifest")}
        events = read("event_master")
        series = read("grid_pentad", [*series_keys, "smp", "p_mm", "p95_mm", "p95_usable"], events=events)
        person, exits, gate = encode_exits(events, series, params, blocks)
        result.update(route2_person_pentad=person, route2_exit=exits)
        result["route2_sample_audit"], result["route2_cif"] = [], []
        result["route2_model_result"] = []
        settings = params["route2"]
        gate["sensitivity"] = {}
        horizons = {"main": settings["h"], **params["sensitivity"]["followup"]}
        for version, horizon in horizons.items():
            if version == "main":
                followup, outcomes, outcome_gate = person, exits, gate
            else:
                followup, outcomes, outcome_gate = encode_exits(
                    events, series, params, blocks, horizon=horizon, version=version)
                gate["sensitivity"][version] = outcome_gate
            audit, support = sample_audit(events, outcomes, blocks, settings)
            outcome_gate.update(support)
            result["route2_sample_audit"].extend(
                dict(row, route2_version=version, H=horizon) for row in audit)
            if outcome_gate["status"] != "exited":
                outcome_gate["time_baseline"] = {}
                for strict in (False, True):
                    curve = cumulative_incidence(followup, horizon, strict=strict)
                    result["route2_cif"].extend(
                        dict(row, route2_version=version, H=horizon, strict=strict)
                        for row in curve)
                    model, diagnostics = fit_cause_specific(curve, horizon, settings["time_df"],
                                                           params["infer"]["epv_min"])
                    outcome_gate["time_baseline"]["strict" if strict else "main"] = diagnostics
                    result["route2_model_result"].extend(
                        dict(row, route2_version=version, H=horizon, strict=strict) for row in model)
                outcome_gate["reasons"].append("暴露效应及正式区间待验收")
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
        batches = pq.ParquetFile(tables["grid_pentad"]).iter_batches(
            columns=[*series_keys, "smp", "p_mm", "p95_mm", "p95_usable"])
        review = review_events(events, (row for batch in batches for row in batch.to_pylist()), params)
        result["review_event_recalc"] = review
        result["missing_exclusion_unknown_summary"] = summarize_missing(events)
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
        checks = [row["passed"] for row in review]
        if schema is not None:
            totals, validation = review_handoffs(tables, schema)
            result["review_table_totals"] = totals
            details["handoff_audit_passed"] = all(row["passed"] for row in (*totals, *validation.values()))
            checks.append(details["handoff_audit_passed"])
            atomic_write(stage / "review_schema_validation.json", json_bytes(validation))
        status = "descriptive_only" if all(checks) else "failed"
    return result, status, details


def arrow_table(name, rows, definition, schema=None):
    """依登记字段顺序转换并检查当前批次的主键。"""
    import pyarrow as pa

    columns = definition["columns"]
    primary = definition.get("primary_key", [])
    if primary:
        keys = [tuple(row.get(name) for name in primary) for row in rows]
        if any(None in key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError(f"主键缺失或重复：{name}")
    return pa.table({column: [row.get(column) for row in rows] for column in columns}, schema=schema)


def write_table(path, rows, definition):
    """依登记字段顺序写表，校验主键，空表保留字段。"""
    import pyarrow.parquet as pq

    pq.write_table(arrow_table(path.stem, rows, definition), path)


def write_climatology(stage, path, support, params, combo, definitions, progress=None):
    """按完整格点时间序列计算 M3，逐批写入三张大表。"""
    from contextlib import ExitStack
    from itertools import groupby, islice

    import pyarrow as pa
    import pyarrow.parquet as pq
    from src.M3.scr_build_climatology import build_climatology

    names = ("grid_climatology", "grid_pentad", "grid_active_pentad")
    passthrough = set(definitions["grid_pentad"]["columns"])
    source_fields = pq.ParquetFile(path).schema_arrow
    columns = [field.name for field in source_fields if field.name in passthrough]
    source = pq.read_table(path, columns=columns).sort_by([("grid_id", "ascending"), ("t_abs", "ascending")])
    types = {field.name: field.type for field in source.schema}
    for data_type, fields in (
        (pa.string(), "product_code product_combo soil_product precip_product clim_version phenology_mode "
                      "land_cover climatology_qc_status"),
        (pa.int64(), "clim_start_year clim_end_year sm_n balance_n p_n p_nonzero_n sm_rank_n p95_n "
                     "balance_rank_n active_window_length_L"),
        (pa.float64(), "p_zero_fraction p95_mm smp balance_p w"),
        (pa.bool_(), "p95_usable active_flag phenology_fallback"),
    ):
        types.update(dict.fromkeys(fields.split(), data_type))
    schemas = [pa.schema([(column, types.get(column, pa.null()))
                          for column in definitions[name]["columns"]]) for name in names]
    rows = (row for batch in source.to_batches(max_chunksize=8192) for row in batch.to_pylist())
    groups = (list(group) for key, group in groupby(rows, key=lambda row: row["grid_id"])
              if key in support and support[key]["mask_include"])
    with ExitStack() as stack:
        writers = [stack.enter_context(pq.ParquetWriter(stage / f"{name}.parquet", schema))
                   for name, schema in zip(names, schemas)]
        done = 0
        while batch := list(islice(groups, 16)):
            outputs = build_climatology((row for group in batch for row in group), support, params, combo)
            for name, result, schema, writer in zip(names, outputs, schemas, writers):
                writer.write_table(arrow_table(name, result, definitions[name], schema))
            done += len(batch)
            emit(progress, "M3", "气候态归并", done=done, unit="格点")


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
    route1_reports = {"q1_recovery_risk": "q1_recovery_risk.csv",
                      "trend_estimate": "q1_trend_result.csv", "q2_lag_result": "q2_lag_result.csv"}
    with index_lock(logs / ".downstream.lock"):
        supplements, evidence = registered_inputs(root, registration, digest)
        m2_path = logs / "module_io_M2.json"
        index_outputs(json.loads(m2_path.read_bytes()))
        base_inputs = [item(m2_path), *evidence]
        downstream = plan["modules"][3:]
        for module in downstream:
            started = monotonic()
            emit(progress, module, "核对交接")
            stage_dir = destination / module
            receipt_path = stage_dir / "module_io.json"
            blocked = [key for key in dag[module]["requires"]
                       if statuses.get(key) not in ("passed", "descriptive_only", "exited")]
            if blocked:
                statuses[module] = "conditional_skipped"
                update_status(logs, module, statuses[module])
                atomic_write(logs / f"module_io_{module}.json", json_bytes(dict(
                    run_id=record["run_id"], module_id=module, status="conditional_skipped",
                    details={"blocked_by": blocked}, input_files=[], output_files=[])))
                emit(progress, module, "上游未放行", "、".join(blocked), state="conditional_skipped")
                continue
            inputs = [*base_inputs, *(item(destination / key / "module_io.json")
                                      for key in dag[module]["requires"] if key not in ("M0", "M1", "M2"))]
            reused = receipt_path.exists()
            if reused:
                receipt = json.loads(receipt_path.read_bytes())
                if receipt["run_id"] != record["run_id"] or receipt["input_files"] != inputs:
                    raise ValueError(f"{module} 输入已变化，请使用新别名。")
                index_outputs(receipt)
            else:
                if stage_dir.exists():
                    raise ValueError(f"{module} 目录已存在且缺少冻结回执。")
                destination.mkdir(parents=True, exist_ok=True)
                try:
                    with TemporaryDirectory(dir=destination, prefix=".stage-") as tmp:
                        stage = Path(tmp) / module
                        stage.mkdir()
                        emit(progress, module, "执行计算")
                        result, status, details = compute_module(module, tables, supplements, params, plan, matrix,
                                                                 stage=stage, schema=schema, progress=progress)
                        emit(progress, module, "写入产物")
                        for name, rows in result.items():
                            definition = schema["event_master" if name == "event_master_base" else name]
                            write_table(stage / f"{name}.parquet", rows, definition)
                        if module == "M7":
                            for name, filename in route1_reports.items():
                                atomic_write(stage / filename, csv_bytes(schema[name]["columns"], result[name]))
                        if module == "M8":
                            atomic_write(stage / "route2_gate.json", json_bytes(details))
                            for name in ("route2_sample_audit", "route2_cif", "route2_model_result"):
                                if result[name]:
                                    atomic_write(stage / f"{name}.csv",
                                                 csv_bytes(schema[name]["columns"], result[name]))
                            lines = ["# 路线二出口审计", "", f"状态为 {status}。", "",
                                     *(f"- {reason}" for reason in details["reasons"])]
                            atomic_write(stage / "route2_exit_report.md", ("\n".join(lines) + "\n").encode("utf-8"))
                        if "sample_flow" in result:
                            atomic_write(stage / "sample_flow.csv",
                                         csv_bytes(schema["sample_flow"]["columns"], result["sample_flow"]))
                        if module == "M10":
                            from src.M10.scr_audit_handoffs import review_deviations

                            deviation = (logs / "deviation_log.csv").read_bytes()
                            if sha256(deviation).hexdigest() != record["input_sha256"]["config/deviation_log.csv"]:
                                raise ValueError("冻结偏离登记副本哈希不符。")
                            columns = schema["deviation_log"]["columns"]
                            deviation_rows = review_deviations(deviation, columns)
                            atomic_write(stage / "review_deviation_audit.csv",
                                         csv_bytes([*columns, "review_status"], deviation_rows))
                            details["deviation_review_status"] = {
                                row["deviation_id"]: row["review_status"] for row in deviation_rows}
                            if any(row["review_status"] == "requires_review" for row in deviation_rows):
                                status = "failed"
                            report = ["# 路线一复核记录", "", f"运行身份为 {record['run_id']}。",
                                      f"复核状态为 {status}。", "",
                                      f"完成 {details['reviewed']} 条事件复核，目标为 {details['review_target']} 条。",
                                      f"冻结交接核对{'通过' if details['handoff_audit_passed'] else '失败'}。", "",
                                      "待完成项目", "", *(f"- {entry}" for entry in details["pending"])]
                            atomic_write(stage / "final_reproducibility_report.md",
                                         ("\n".join(report) + "\n").encode("utf-8"))
                            for name in ("review_event_recalc", "review_table_totals",
                                         "missing_exclusion_unknown_summary"):
                                atomic_write(stage / f"{name}.csv",
                                             csv_bytes(schema[name]["columns"], result[name]))
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
                        emit(progress, module, "核验输入输出哈希")
                        outputs = [{"path": (stage_dir / path.relative_to(stage)).relative_to(root).as_posix(),
                                    "sha256": digest(path)}
                                   for path in sorted(stage.rglob("*")) if path.is_file()]
                        for entry in inputs:
                            verify_file(root, entry, digest)
                        receipt = dict(run_id=record["run_id"], module_id=module, status=status, details=details,
                                       input_files=inputs, output_files=outputs)
                        atomic_write(stage / receipt_path.name, json_bytes(receipt))
                        emit(progress, module, "发布冻结交接")
                        stage.rename(stage_dir)
                    index_outputs(receipt)
                except Exception:
                    update_status(logs, module, "failed")
                    raise
            statuses[module] = receipt["status"]
            emit(progress, module, "发布交接与报告")
            atomic_write(logs / f"module_io_{module}.json", json_bytes(receipt))
            update_status(logs, module, receipt["status"])
            stamp = datetime.now(timezone.utc).isoformat()
            event = dict(time=stamp, level="INFO", message=f"{module} 交接状态已登记",
                         status=receipt["status"], runtime=plan.get("runtime"),
                         elapsed_seconds=monotonic() - started)
            atomic_write(logs / module / f"{stamp.replace(':', '-')}.jsonl", json_bytes(event))
            if module == "M7":
                for filename in route1_reports.values():
                    atomic_write(output / "tables" / filename, (stage_dir / filename).read_bytes())
            if module == "M8":
                for name in ("route2_sample_audit.csv", "route2_cif.csv", "route2_model_result.csv",
                             "route2_gate.json", "route2_exit_report.md"):
                    source = stage_dir / name
                    if source.is_file():
                        category = "tables" if source.suffix == ".csv" else "reports"
                        atomic_write(output / category / name, source.read_bytes())
            if module == "M10":
                for name in ("review_event_recalc.csv", "review_table_totals.csv", "review_schema_validation.json",
                             "review_deviation_audit.csv"):
                    atomic_write(output / "review" / name, (stage_dir / name).read_bytes())
                summary = stage_dir / "missing_exclusion_unknown_summary.csv"
                atomic_write(output / "tables" / summary.name, summary.read_bytes())
                report = stage_dir / "final_reproducibility_report.md"
                atomic_write(output / "reports" / report.name, report.read_bytes())
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
            state = receipt["status"]
            emit(progress, module, "模块结束",
                 state="reused" if reused and state in {"passed", "descriptive_only"} else state)
    return {**plan, "run_id": record["run_id"], "module_status": statuses, "downstream": str(destination), "m1_reports": upstream["m1_reports"]}
