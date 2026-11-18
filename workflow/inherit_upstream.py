"""为仅修复M7求解器的新身份登记只读M1–M6继承；不复制或改写源数据。"""
import ast
import json
from pathlib import Path

from .freeze_m0 import atomic_write, json_bytes
from .run_era5land import frozen_context, update_status


MODULES = tuple(f"M{i}" for i in range(1, 7))
ALLOWED_CODE = {
                "workflow/inherit_upstream.py", "workflow/run_module.py", "workflow/run_downstream.py",
                "workflow/terminal_panel.py", "workflow/progress.py"}


def upstream_projection(name, text):
    """仅剔除明确属于M7的新增设置，其他配置变化一律拒绝继承。"""
    import yaml
    value = yaml.safe_load(text)
    if name == "config/params.yaml":
        for section, keys in {
            "route1": ("q1_censor_sensitivities", "model_sensitivities", "e1a", "supplements"),
            "infer": ("year_score_bootstrap", "year_score_calibration", "target_power"),
            "gam": ("min_reference_n_eff", "min_fit_n_eff"),
            "psm": ("output_scope", "common_support_refit_max"),
            "sensitivity": ("block_km", "reduced_soil_terrain_drop"),
        }.items():
            for key in keys:
                value.get(section, {}).pop(key, None)
    elif name == "config/specification_matrix.yaml":
        value.pop("m7_model_sensitivities", None)
        value.pop("m7_supplements", None)
        value["selectable_variants"] = sorted(value["selectable_variants"])
        for key in ("main", "lai_four_of_five"):
            value.get("variant_labels", {}).get(key, {}).pop("label", None)
    elif name == "config/schema_registry.yaml":
        # M1–M6交接表必须原样；只剔除本轮登记的M7输出。
        allowed = {"q1_recovery_risk", "q1_recovery_risk_sensitivity", "q1_curve_uncertainty", "q1_recovery_distribution",
            "q1_censor_audit", "q1_annual_companions", "q1_companion_trend",
            "route1_year_wild_sensitivity", "sensitivity_model_manifest", "sensitivity_model_result",
            "sensitivity_model_marginal", "sensitivity_model_uncertainty", "sensitivity_year_wild", "model_diagnostics",
            "e1a_grid_year", "e1a_frequency_model", "fz_grid_year", "fz_spatial", "dfai_distribution",
            "psm_pairs", "psm_balance", "psm_contrast"}
        for key in allowed:
            value["tables"].pop(key, None)
        # 仅允许主模型清单追加两个诊断列，其他原字段仍核对。
        columns = value["tables"]["model_fit_manifest"]["columns"]
        value["tables"]["model_fit_manifest"]["columns"] = [c for c in columns if c not in ("outcome_sd", "weight_kish")]
        columns = value["tables"]["model_marginal"]["columns"]
        value["tables"]["model_marginal"]["columns"] = [c for c in columns if c not in ("predicted_response", "response_difference")]
    else:
        raise ValueError(f"未登记配置投影：{name}")
    return value


def checked_item(root, entry, digest):
    """核验项目内不可覆盖的来源文件。"""
    path = (root / entry["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file() or digest(path) != entry["sha256"]:
        raise ValueError(f"继承来源文件哈希不符或缺失：{entry['path']}")
    return path


def validate_receipt_chain(root, path, module, params, digest, seen=None):
    """逐层验证继承回执到原始冻结回执，防止循环及来源链断裂。"""
    seen = set() if seen is None else seen
    path = path.resolve()
    if path in seen or not path.is_relative_to(root.resolve()):
        raise ValueError("继承回执链循环或越界。")
    seen.add(path)
    receipt = json.loads(path.read_bytes())
    for item in receipt["output_files"]:
        checked_item(root, item, digest)
    if receipt.get("execution_mode") == "inherited_readonly":
        references = receipt["input_files"]
        if len(references) != 1:
            raise ValueError("继承回执必须有唯一来源。")
        parent_path = checked_item(root, references[0], digest)
        parent = validate_receipt_chain(root, parent_path, module, params, digest, seen)
        if (parent["run_id"] != receipt["source_run_id"] or parent["status"] != receipt["status"]
                or parent["output_files"] != receipt["output_files"]):
            raise ValueError("继承链的来源身份或产物不一致。")
    elif module not in ("M1", "M2"):
        canonical = root / params["output"]["frozen"] / "downstream" / path.parent.name / module / "module_io.json"
        if not canonical.is_file() or canonical.read_bytes() != path.read_bytes():
            raise ValueError(f"源{module}的日志与冻结回执不一致。")
    return receipt


def progress_only_change(previous, current):
    """只忽略独立进度上报语句，禁止借上报表达式插入调用。"""
    class StripProgress(ast.NodeTransformer):
        def visit_Expr(self, node):
            call = node.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "emit":
                if any(isinstance(part, (ast.Call, ast.Await, ast.Yield, ast.NamedExpr))
                       for arg in (*call.args, *(item.value for item in call.keywords))
                       for part in ast.walk(arg)):
                    raise ValueError("进度事件参数不得包含函数调用或副作用。")
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)
    try:
        def normalized(source):
            tree = StripProgress().visit(ast.parse(source))
            # 允许添加或移除独立事件，其他语句与结构必须一致。
            for node in ast.walk(tree):
                for field, value in ast.iter_fields(node):
                    if isinstance(value, list):
                        setattr(node, field, [item for item in value if not isinstance(item, ast.Pass)])
            return ast.dump(tree, include_attributes=False)
        return normalized(previous) == normalized(current)
    except (SyntaxError, ValueError):
        return False


def source_context(root, plan, config_path, params, source_alias, digest):
    """检查源身份、同方案和严格允许的M7代码差异，拒绝上游科学变更。"""
    from .run_module import validate_alias

    source_alias = validate_alias(source_alias)
    if source_alias == plan["run_alias"]:
        raise ValueError("继承源与新别名必须不同。")
    source_plan = {**plan, "run_alias": source_alias, "run_id": None}
    context = frozen_context(root, source_plan, config_path, params, digest, historical=True)
    record = context[0]
    for name, expected in record["input_sha256"].items():
        if name == "config/deviation_log.csv":
            if not (root / name).read_bytes().decode("utf-8").startswith(record["input_snapshot"][name]):
                raise ValueError("继承只允许追加偏离记录，不能改写历史偏离。")
        elif digest(root / name) != expected:
            if name not in {"config/params.yaml", "config/schema_registry.yaml", "config/specification_matrix.yaml"} or (
                upstream_projection(name, (root / name).read_text(encoding="utf-8")) !=
                upstream_projection(name, record["input_snapshot"][name])):
                raise ValueError(f"上游冻结配置改变，禁止继承：{name}")
    current = {p.relative_to(root).as_posix(): digest(p) for folder in ("src", "workflow")
               for p in (root / folder).rglob("*.py")}
    changed = {k for k in current.keys() | record["code_files"].keys()
               if current.get(k) != record["code_files"].get(k)}
    forbidden = {k for k in changed if k not in ALLOWED_CODE and not k.startswith("src/M7/")}
    display_code = "workflow/run_era5land.py"
    if display_code in forbidden:
        previous = record.get("code_snapshot", {}).get(display_code)
        if previous is not None and progress_only_change(previous, (root / display_code).read_text(encoding="utf-8")):
            forbidden.remove(display_code)
    if forbidden:
        raise ValueError(f"超出M7修订继承范围：{sorted(forbidden)}")
    return context, sorted(changed)


def selected_modules(through):
    """只开放已接入下游编排的连续 M1–M2 至 M1–M6。"""
    if through not in {f"M{i}" for i in range(2, 7)}:
        raise ValueError("继承终点目前仅支持 M2–M6。")
    return MODULES[:int(through[1:])]


def check_source_receipts(root, source, params, digest, modules):
    """冻结新别名前验证完整源回执，避免无效接力留下半成品。"""
    old, _, _, old_logs, _ = source
    for module in modules:
        receipt = validate_receipt_chain(root, old_logs / f"module_io_{module}.json", module, params, digest)
        allowed = {"passed", "descriptive_only"} if module == "M6" else {"passed"}
        if receipt["run_id"] != old["run_id"] or receipt["status"] not in allowed:
            raise ValueError(f"源{module}没有通过验收。")


def prepare_inheritance(root, plan, config_path, params, source_alias, digest):
    """新M0冻结后发布继承回执；清单最后发布，支持安全重试。"""
    source, changed = source_context(root, plan, config_path, params, source_alias, digest)
    target = frozen_context(root, plan, config_path, params, digest)
    old, _, old_output, old_logs, _ = source
    record, _, _, logs, _ = target
    modules = selected_modules(plan.get("inherit_through", "M6"))
    check_source_receipts(root, source, params, digest, modules)
    entries = []
    for module in modules:
        path = old_logs / f"module_io_{module}.json"
        receipt = validate_receipt_chain(root, path, module, params, digest)
        allowed_status = {"passed", "descriptive_only"} if module == "M6" else {"passed"}
        if receipt["run_id"] != old["run_id"] or receipt["status"] not in allowed_status:
            raise ValueError(f"源{module}没有通过验收。")
        for item in receipt["output_files"]:
            checked_item(root, item, digest)
        reference = {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}
        wrapper = {"module_id": module, "run_id": record["run_id"], "status": receipt["status"],
                   "execution_mode": "inherited_readonly", "source_run_id": old["run_id"],
                   "input_files": [reference], "output_files": receipt["output_files"],
                   "details": {"source_alias": source_alias, "recomputed": False}}
        wrapper_path = logs / f"module_io_{module}.json"
        atomic_write(wrapper_path, json_bytes(wrapper))
        entries.append({"module": module, "source_receipt": reference,
                        "receipt": {"path": wrapper_path.relative_to(root).as_posix(), "sha256": digest(wrapper_path)}})
    manifest = {"run_id": record["run_id"], "source_alias": source_alias,
                "source_run_id": old["run_id"], "allowed_target": "M7", "inherit_through": modules[-1], "changed_code": changed,
                "source_freeze": {"path": (old_output / "protocol_freeze.json").relative_to(root).as_posix(),
                                  "sha256": digest(old_output / "protocol_freeze.json")}, "modules": entries}
    atomic_write(logs / "upstream_inheritance.json", json_bytes(manifest))
    for module in modules:
        update_status(logs, module, json.loads((logs / f"module_io_{module}.json").read_bytes())["status"])
    return manifest


def load_inheritance(root, plan, config_path, params, digest):
    """执行前重新核验全部继承输出；不重新读取或处理原始产品。"""
    path = root / params["output"]["logs"] / plan["run_alias"] / "upstream_inheritance.json"
    if not path.exists():
        return None
    if not plan["resume"] or plan["modules"] != [f"M{i}" for i in range(len(plan["modules"]))] or not 4 <= len(plan["modules"]) <= 8:
        raise ValueError("本次继承仅支持续跑至M7或更早的下游模块；M8–M10尚未验收继承接口。")
    context = frozen_context(root, plan, config_path, params, digest)
    manifest = json.loads(path.read_bytes())
    if manifest["run_id"] != context[0]["run_id"]:
        raise ValueError("继承清单与当前冻结身份不匹配。")
    checked_item(root, manifest["source_freeze"], digest)
    source, changed = source_context(root, plan, config_path, params, manifest["source_alias"], digest)
    if source[0]["run_id"] != manifest["source_run_id"] or changed != manifest["changed_code"]:
        raise ValueError("继承来源身份或代码差异改变。")
    modules = selected_modules(manifest.get("inherit_through", "M6"))
    if [entry["module"] for entry in manifest["modules"]] != list(modules) or int(modules[-1][1:]) >= len(plan["modules"]) - 1:
        raise ValueError("继承清单与执行范围不匹配，须运行继承终点之后的模块。")
    receipts = {}
    for entry in manifest["modules"]:
        source_receipt = validate_receipt_chain(root, checked_item(root, entry["source_receipt"], digest),
                                               entry["module"], params, digest)
        receipt = json.loads(checked_item(root, entry["receipt"], digest).read_bytes())
        allowed_status = {"passed", "descriptive_only"} if entry["module"] == "M6" else {"passed"}
        if (source_receipt["run_id"] != manifest["source_run_id"] or source_receipt["status"] not in allowed_status
                or receipt["run_id"] != manifest["run_id"] or receipt["status"] != source_receipt["status"]
                or receipt["output_files"] != source_receipt["output_files"]):
            raise ValueError("继承模块身份或源产物不一致。")
        for item in receipt["output_files"]:
            checked_item(root, item, digest)
        receipts[entry["module"]] = receipt
    return {"context": context, "manifest": manifest, "receipts": receipts,
            "reference": {"path": path.relative_to(root).as_posix(), "sha256": digest(path)}}
