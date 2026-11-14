"""核验 M5 活跃窗修订与同别名的已冻结上游交接。"""
import json

from .run_era5land import frozen_context


def load_m5_revision(root, plan, config_path, params, load_config, digest):
    """仅允许已登记的 M5 修订范围，返回可审计的代码与交接引用。"""
    alias = plan["run_alias"]
    path = root / params["output"]["outputs"] / alias / "protocol_freeze.json"
    if not path.is_file():
        return None
    frozen = json.loads(path.read_bytes())
    if "M6" in plan["modules"]:
        revision_path = root / params["output"]["logs"] / alias / "m5_code_revision.json"
        if revision_path.is_file():
            return load_after_m5(root, plan, config_path, params, load_config, digest, frozen, revision_path)
    old_files = frozen["code_files"]
    current_files = {p.relative_to(root).as_posix(): digest(p)
                     for directory in ("src", "workflow")
                     for p in (root / directory).rglob("*.py")}
    changes = {key for key in current_files.keys() | old_files.keys()
               if current_files.get(key) != old_files.get(key)}
    if "src/M5/scr_derive_outcomes.py" not in changes:
        return None
    allowed = {"src/M5/scr_derive_outcomes.py", "src/M7/scr_route1_summary.py",
               "src/M10/scr_audit_handoffs.py", "workflow/run_downstream.py",
               "workflow/run_era5land.py", "workflow/resume_m5.py"}
    if changes - allowed:
        raise ValueError(f"M5 修订范围外的代码已变化：{sorted(changes - allowed)}")
    if changes - current_files.keys():
        raise ValueError("M5 修订缺少代码文件。")
    context = frozen_context(root, plan, config_path, params, digest, historical=True)
    record, _, _, logs, _ = context
    schema_key = "config/schema_registry.yaml"
    for key, checksum in record["input_sha256"].items():
        if key != schema_key and digest(root / key) != checksum:
            raise ValueError(f"M5 修订不可复用已变化的冻结输入：{key}")
    old_schema = load_config(root / schema_key, content=record["input_snapshot"][schema_key].encode("utf-8"))
    tables = old_schema["tables"]
    fields = tables["event_master"]["columns"]
    fields.insert(fields.index("F_R_subtype") + 1, "route1_FR_eligible")
    fields = tables["q2_annual"]["columns"]
    fields.insert(fields.index("proportion"), "n_outside_active_window")
    if old_schema != load_config(root / schema_key):
        raise ValueError("Schema 变化超出 M5 活跃窗修订范围。")

    from .run_downstream import verify_file

    references = []
    downstream = root / params["output"]["frozen"] / "downstream" / alias
    for module in ("M1", "M2", "M3", "M4"):
        receipt_path = logs / f"module_io_{module}.json"
        receipt = json.loads(receipt_path.read_bytes())
        if (receipt["run_id"], receipt["module_id"], receipt["status"]) != (record["run_id"], module, "passed"):
            raise ValueError(f"{module} 冻结回执未通过或身份不符。")
        if module in ("M3", "M4"):
            if digest(downstream / module / "module_io.json") != digest(receipt_path):
                raise ValueError(f"{module} 冻结回执与日志副本不符。")
        for entry in receipt["output_files"]:
            verify_file(root, entry, digest)
        references.append({"path": receipt_path.relative_to(root).as_posix(), "sha256": digest(receipt_path)})
        if module == "M1":
            source = root / params["native_era5land"]["evidence"]
            if digest(source) != receipt["evidence_sha256"]:
                raise ValueError("M1 来源登记已变化。")
        if module == "M2" and receipt["input_files"] != references[:1]:
            raise ValueError("M2 的 M1 回执引用不符。")
    manifest = {"base_run_id": record["run_id"], "starts_at": "M5",
                "schema_sha256": digest(root / schema_key), "upstream_receipts": references,
                "code_files": {key: current_files[key] for key in sorted(changes)},
                "code_snapshot": {key: (root / key).read_bytes().decode("utf-8") for key in sorted(changes)}}
    return {"context": context, "manifest": manifest}


def load_after_m5(root, plan, config_path, params, load_config, digest, frozen, revision_path):
    """从已冻结的 M5 继续，检查更改只涉及 M6 及其下游。"""
    from .run_downstream import verify_file

    context = frozen_context(root, plan, config_path, params, digest, historical=True)
    record, _, _, _, _ = context
    directory = root / params["output"]["frozen"] / "downstream" / plan["run_alias"]
    receipt = json.loads((directory / "M5/module_io.json").read_bytes())
    reference = {"path": revision_path.relative_to(root).as_posix(), "sha256": digest(revision_path)}
    if (receipt["run_id"], receipt["status"], receipt["module_id"]) != (record["run_id"], "passed", "M5") or reference not in receipt["input_files"]:
        raise ValueError("M5 冻结回执或修订引用不符。")
    prior = json.loads(revision_path.read_bytes())
    for item in prior["upstream_receipts"]:
        path = verify_file(root, item, digest)
        for output in json.loads(path.read_bytes())["output_files"]:
            verify_file(root, output, digest)

    known = {**frozen["code_files"], **prior["code_files"]}
    current = {p.relative_to(root).as_posix(): digest(p)
               for directory_name in ("src", "workflow") for p in (root / directory_name).rglob("*.py")}
    changed = {key for key in current.keys() | known.keys() if current.get(key) != known.get(key)}
    if changed - current.keys() or any(
        not key.startswith(("src/M6/", "src/M7/"))
        and key not in {"workflow/run_downstream.py", "workflow/resume_m5.py", "src/M10/scr_audit_handoffs.py",
                        "workflow/progress.py", "workflow/run_module.py", "workflow/terminal_panel.py"}
        for key in changed
    ):
        raise ValueError("检测到超出 M6 接续范围的代码变更。")

    snapshots = {}
    for key, checksum in record["input_sha256"].items():
        file = root / key
        if digest(file) == checksum:
            continue
        content = file.read_bytes()
        snapshots[key] = content.decode("utf-8")
        old = record["input_snapshot"][key].encode("utf-8")
        if key == "config/params.yaml":
            expected = load_config(file, content=old)
            expected["lai"].update({k: params["lai"][k] for k in ("mask_version", "qc_version")})
            expected["route1"]["deep_marginal_quantiles"] = params["route1"]["deep_marginal_quantiles"]
            expected["block"]["bootstrap_min_success_fraction"] = params["block"]["bootstrap_min_success_fraction"]
            compatible = expected == params
        elif key == "config/schema_registry.yaml":
            old_tables = load_config(file, content=old)["tables"]
            new_tables = load_config(file, content=content)["tables"]
            old_tables["event_master"]["columns"].insert(old_tables["event_master"]["columns"].index("F_R_subtype") + 1, "route1_FR_eligible")
            for name in ("model_fit_manifest", "model_result", "model_marginal", "route1_model_uncertainty",
                         "grid_static_covariates", "q2_annual", "q2_lag_result", "q2_fr_grid_year", "q2_fr_spatial"):
                if name in new_tables:
                    old_tables[name] = new_tables[name]
            compatible = old_tables == new_tables
        elif key == "config/deviation_log.csv":
            from csv import DictReader
            from io import StringIO

            before = list(DictReader(StringIO(old.decode("utf-8-sig"))))
            after = list(DictReader(StringIO(content.decode("utf-8-sig"))))
            compatible = after[:len(before)] == before and all(row["affected_modules"] == "M7" for row in after[len(before):])
        else:
            compatible = False
        if not compatible:
            raise ValueError(f"M6 接续不可复用已变化的冻结输入：{key}")
    manifest = dict(base_run_id=record["run_id"], starts_at="M6", previous_revision=reference,
                    code_files={key: current[key] for key in sorted(changed)},
                    code_snapshot={key: (root / key).read_text(encoding="utf-8") for key in sorted(changed)},
                    input_snapshot=snapshots)
    return {"context": context, "manifest": manifest, "previous": reference}
