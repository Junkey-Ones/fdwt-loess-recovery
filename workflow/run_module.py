"""脚本名：run_module.py（编排层 · 统一运行入口）

功能简介：验证运行计划，调度 M0 冻结及 ERA5-Land M1/M2。
作者：Codex
版本：v0.1.0
读取数据：config 下的参数与规范矩阵、workflow/dag.yaml、logs 下的运行登记。
生成数据：M0 冻结前审计 JSONL。
其他文件：进度和错误发送到标准错误。
运行示例：python -m workflow.run_module
退出码：0 计划有效，1 执行失败，2 预检失败，130 中断。
"""
import argparse
import csv
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from tempfile import NamedTemporaryFile
from uuid import uuid4

import yaml

from .terminal_panel import ChineseHelp, ChineseParser, LiveStatus, WizardBack, WizardPanel, check_progress, validate_progress


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "params.yaml"


def load_config(path, *, content=None):
    """读取 UTF-8 YAML 映射。返回配置字典，不补写科学参数。"""
    if content is None:
        content = Path(path).read_bytes()
    config = yaml.safe_load(content.decode("utf-8-sig"))
    if not isinstance(config, dict):
        raise ValueError(f"配置必须为 YAML 映射：{path}")
    return config


def validate_alias(alias):
    """检查必填别名的日期、Windows 路径字符和末尾字符。返回原别名。"""
    if not alias or not re.fullmatch(r'\d{4}-\d{2}-\d{2}_[^<>:"/\\|?*\x00-\x1f]+', alias):
        raise ValueError("请输入 YYYY-MM-DD_短描述 格式的运行别名。")
    try:
        date.fromisoformat(alias[:10])
    except ValueError:
        raise ValueError("运行别名前缀必须是真实的日期。") from None
    if alias.endswith((".", " ")) or not alias[11:].strip():
        raise ValueError("短描述不能为空，也不能以点或空格结尾。")
    return alias


def plan_modules(dag, targets):
    """按依赖排序目标模块。只在选中可选模块时加入相应依赖。"""
    modules = dag["modules"]
    ordered = []
    visiting = set()
    requested = set()

    def visit(module, include_optional=False):
        if module not in modules:
            raise ValueError(f"未知模块：{module}")
        if module in visiting:
            raise ValueError(f"模块依赖存在循环：{module}")
        if module in ordered:
            return
        visiting.add(module)
        info = modules[module]
        for dependency in info["requires"]:
            visit(dependency, include_optional)
        if include_optional:
            for dependency in info.get("optional", []):
                if dependency in requested:
                    visit(dependency, include_optional)
        visiting.remove(module)
        ordered.append(module)

    for target in targets:
        visit(target)
    requested.update(ordered)
    ordered.clear()
    for target in targets:
        visit(target, include_optional=True)
    return ordered


def build_run_id(params, params_hash, code_hash):
    """根据协议、参数和代码 SHA-256 及登记种子标识生成运行身份。"""
    seed = params["random"]
    if seed["seed"] is None or not seed["seed_id"]:
        raise ValueError("随机种子须由 M0 正式登记后才能运行。")
    return f'{params["protocol"]["version"]}__{params_hash[:12]}__{code_hash[:12]}__{seed["seed_id"]}'


def variant_options(matrix):
    """从已登记方案读取中文标签，面板不收集自由科学阈值。"""
    labels = matrix.get("variant_labels", {})
    return [(key, labels.get(key, {}).get("label", key), labels.get(key, {}).get("description", ""))
            for key in matrix["selectable_variants"]]


def run_m0_audit(plan, config_path, params, matrix, params_bytes, matrix_bytes, formal_freeze, progress=None):
    """收集只读审计输入并将单次审计明细原子封存到日志目录。"""
    from src.M0.scr_audit_protocol import audit_protocol

    matrix_path = "config/specification_matrix.yaml"
    schema_path = "config/schema_registry.yaml"
    freeze_path = "metadata/protocol_freeze.yaml"
    document_dir = Path("docs/论文方向与构想")
    version = params["protocol"]["version"]
    if not isinstance(version, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", version):
        raise ValueError("协议版本须采用 v主版本.次版本.修订版本 格式。")
    titles = ("预注册文档", "详细技术手册", "分产品原生变量与预处理SOP附录",
              "说明书", "权威文献引用解释", "模块化思路理解", "AI工作包_workflow搭建")
    documents = [(document_dir / f"黄土高原FD-WT_{version}_{title}.md").as_posix()
                 for title in titles]
    paths = [schema_path, freeze_path, "config/deviation_log.csv", "workflow/dag.yaml",
             "metadata/source_file_manifest.csv", "metadata/source_variable_map.csv",
             "metadata/site_boundary_acceptance.csv", "metadata/study_area_manifest.csv", *documents]
    from .progress import emit
    inputs = {}
    for index, path in enumerate(paths):
        emit(progress, "M0", "读取协议与登记", done=index, total=len(paths), unit="文件",
             operation="读取", path=ROOT / path)
        inputs[path] = (ROOT / path).read_bytes()
    boundary_path = "metadata/study_area_rectangle.geojson"
    if (ROOT / boundary_path).is_file():
        inputs[boundary_path] = (ROOT / boundary_path).read_bytes()
    inputs[os.path.relpath(Path(config_path).resolve(), ROOT).replace(os.sep, "/")] = params_bytes
    inputs[matrix_path] = matrix_bytes
    schema = load_config(schema_path, content=inputs[schema_path])
    freeze = load_config(freeze_path, content=inputs[freeze_path])
    report = audit_protocol(params, schema, matrix, freeze, documents, inputs)

    logs_root = (ROOT / params["output"]["logs"]).resolve()
    log_dir = (logs_root / plan["run_alias"] / "M0").resolve()
    if not log_dir.is_relative_to(ROOT / "logs"):
        raise ValueError("M0 审计日志必须位于项目 logs 目录内。")
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%dT%H-%M-%S")
    destination = log_dir / f"M0_scr_audit_protocol_{stamp}_{uuid4().hex}.jsonl"
    event = {
        "level": "ERROR" if report["status"] == "failed" else "INFO",
        "time": now.isoformat(),
        "message": "M0 冻结前审计完成，区域分析未放行",
        "run_alias": plan["run_alias"],
        "runtime": plan["runtime"],
        "stdout": report,
        "stderr": [row["detail"] for row in report["checks"] if row["status"] != "passed"],
    }
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=log_dir, delete=False, suffix=".tmp") as handle:
        temporary = Path(handle.name)
    try:
        emit(progress, "M0", "写入审计日志", operation="写入", path=destination)
        temporary.write_text(json.dumps(event, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    audited = {**plan, "m0_audit": report, "audit_log": str(destination)}
    if formal_freeze:
        from .freeze_m0 import register_freeze

        if report["status"] == "failed":
            return audited
        modules = load_config("workflow/dag.yaml", content=inputs["workflow/dag.yaml"])["modules"]
        return register_freeze(ROOT, audited, params, report, inputs, build_run_id, modules)
    return audited


def run_module(module_id, config_path=DEFAULT_CONFIG, run_id=None, run_alias=None,
               resume=True, overwrite_frozen=False, *, product_combo=None,
               variant="main", dry_run=False, freeze=False, progress=None, runtime=None, inherit_from=None, inherit_through="M6"):
    """统一运行入口。预检只读，正式执行须匹配所选模块的冻结契约。"""
    from .runtime import resolve_runtime

    resources = resolve_runtime(runtime)
    alias = validate_alias(run_alias)
    if overwrite_frozen:
        raise ValueError("冻结产物禁止覆盖。")
    params_bytes = Path(config_path).read_bytes()
    matrix_path = ROOT / "config" / "specification_matrix.yaml"
    matrix_bytes = matrix_path.read_bytes()
    params = load_config(config_path, content=params_bytes)
    matrix = load_config(matrix_path, content=matrix_bytes)
    dag = load_config(ROOT / "workflow" / "dag.yaml")
    targets = dag["targets"].get(module_id, [module_id]) if isinstance(module_id, str) else module_id
    modules = plan_modules(dag, targets)
    product = product_combo or params["products"]["main"]
    if product not in params["products"]["combinations"]:
        raise ValueError("产品组合尚未登记。")
    if variant not in matrix["selectable_variants"]:
        raise ValueError("规范变体尚未放行。")
    plan = {"modules": modules, "run_alias": alias, "run_id": run_id,
            "product_combo": product, "variant": variant, "resume": resume, "runtime": resources}
    if freeze and (dry_run or modules != ["M0"]):
        raise ValueError("正式冻结只能用于单独运行 M0，且不能与预检同时使用。")
    if inherit_from is not None:
        if not freeze or modules != ["M0"]:
            raise ValueError("继承上游只能在新别名单独冻结M0时登记。")
        from .inherit_upstream import selected_modules
        selected_modules(inherit_through)
        plan["inherit_from"] = validate_alias(inherit_from)
        plan["inherit_through"] = inherit_through
    if dry_run:
        return plan
    from contextlib import ExitStack
    from .freeze_m0 import alias_lock

    with ExitStack() as stack:
        try:
            stack.enter_context(alias_lock(ROOT, alias))
        except OSError as error:
            raise ValueError(f"无法锁定运行别名，可能正在运行或清理：{alias}") from error
        if hasattr(progress, "configure_run"):
            progress.configure_run(ROOT, plan, params)
        return execute_plan(plan, config_path, params, matrix, params_bytes, matrix_bytes, freeze, progress)


def execute_plan(plan, config_path, params, matrix, params_bytes, matrix_bytes, freeze, progress):
    """在别名锁保护下调度正式运行。"""
    modules = plan["modules"]
    if modules == ["M0"]:
        if plan["run_id"] is not None and not freeze:
            raise ValueError("冻结前审计只使用运行别名，不能绑定正式 run_id。")
        from .progress import emit

        emit(progress, "M0", "审计协议与登记")
        if plan.get("inherit_from"):
            from .inherit_upstream import source_context, prepare_inheritance, selected_modules, check_source_receipts
            from src.M1.scr_audit_era5land import digest
            source, _ = source_context(ROOT, plan, config_path, params, plan["inherit_from"], digest)
            check_source_receipts(ROOT, source, params, digest, selected_modules(plan["inherit_through"]))
        existing = ROOT / params["output"]["logs"] / plan["run_alias"] / "module_io_M0.json"
        if plan.get("inherit_from") and existing.is_file():
            # 冻结已建立时，复核身份并幂等恢复继承登记，不重置模块状态。
            inherited = prepare_inheritance(ROOT, plan, config_path, params, plan["inherit_from"], digest)
            emit(progress, "M0", "已恢复只读继承", state="passed")
            return {**plan, "run_id": inherited["run_id"], "inheritance": inherited,
                    "m0_audit": {"status": "passed", "formal_freeze_written": True}}
        result = run_m0_audit(plan, config_path, params, matrix, params_bytes, matrix_bytes, freeze, progress)
        if plan.get("inherit_from") and result["m0_audit"].get("formal_freeze_written"):
            emit(progress, "M0", "核验并登记只读上游继承")
            result["inheritance"] = prepare_inheritance(ROOT, plan, config_path, params, plan["inherit_from"], digest)
        emit(progress, "M0", "协议审计结束", state=result["m0_audit"]["status"])
        return result
    if modules in (["M0", "M1"], ["M0", "M1", "M2"]):
        from .run_era5land import run_era5land

        return run_era5land(ROOT, plan, config_path, params, load_config,
                            progress or (lambda *_: None))
    from .run_downstream import run_downstream

    return run_downstream(ROOT, plan, config_path, params, load_config, progress or (lambda *_: None))


def wizard(args, panel):
    """按中文问答收集与高级入口共用的控制信息。"""
    from .runtime import resolve_runtime, runtime_lines

    dag = load_config(ROOT / "workflow" / "dag.yaml")
    params = load_config(args.config_path)
    matrix = load_config(ROOT / "config" / "specification_matrix.yaml")
    names = tuple(f"{key} {info['name']}" for key, info in dag["modules"].items())

    def scope(value):
        modules = list(dict.fromkeys(re.split(r"[\s,，、]+", (value or "").strip().upper())))
        modules = [module for module in modules if module]
        if not modules:
            raise ValueError("请选择至少一个模块。")
        plan_modules(dag, modules)
        return modules

    args.inherit_from = None
    args.inherit_through = "M6"

    def choose_scope():
        target = panel.menu("选择运行范围", (
            ("route1", "路线一主分析", "M0–M7、M9–M10"),
            ("full", "完整工作流", "M0–M10，包含 M8 路线二"),
            ("custom", "指定模块", "选择一个或多个模块，自动纳入必需的上游依赖"),
        ), "full", section="01/05  运行范围")
        args.modules = [target]
        if target == "custom":
            selected = set()
            while True:
                choices = tuple((key, f"{'☑' if key in selected else '☐'} {key} {info['name']}", "选择或取消")
                                for key, info in dag["modules"].items())
                chosen = panel.menu("选择目标模块（可多选）", (*choices, ("done", "完成选择", "自动包含上游依赖")),
                                    "done" if selected else "M7", section="01/05  运行范围")
                if chosen == "done":
                    if selected:
                        break
                    continue
                if chosen in selected:
                    selected.remove(chosen)
                else:
                    selected.add(chosen)
            args.modules = [key for key in dag["modules"] if key in selected]

    def choose_version():
        args.run_alias = panel.ask("输入运行别名", validate_alias, section="02/05  运行版本",
                                   hint="格式 YYYY-MM-DD_短描述，例如 2026-11-10_主分析")
        run_logs = ROOT / params["output"]["logs"] / args.run_alias
        status = run_logs / "module_status.csv"
        args.new = not status.is_file()
        args.inherit_from = None
        targets = dag["targets"].get(args.modules[0], args.modules)
        ordered = plan_modules(dag, targets)
        index_path = ROOT / "metadata/run_index.csv"
        candidates = []
        if args.new and 4 <= len(ordered) <= 8 and ordered == [f"M{i}" for i in range(len(ordered))] and index_path.is_file():
            with index_path.open(encoding="utf-8-sig", newline="") as handle:
                for row in csv.DictReader(handle):
                    alias = row.get("run_alias", "")
                    try:
                        validate_alias(alias)
                    except ValueError:
                        continue
                    source_logs = ROOT / params["output"]["logs"] / alias
                    available = []
                    for i in range(1, min(6, len(ordered) - 2) + 1):
                        receipt = source_logs / f"module_io_M{i}.json"
                        try:
                            data = json.loads(receipt.read_bytes())
                            if data.get("status") not in ({"passed", "descriptive_only"} if i == 6 else {"passed"}):
                                break
                        except (OSError, ValueError):
                            break
                        available.append(f"M{i}")
                    if len(available) >= 2 and alias != args.run_alias:
                        candidates.append((alias, available))
        if candidates and panel.menu("选择上游数据", (("new", "从头运行", "先冻结 M0"), ("reuse", "复用已有运行", "验证后只读接力")), "reuse", section="02/05  运行版本") == "reuse":
            args.inherit_from = panel.menu("选择来源别名", tuple((alias, alias, f"可用 M1–{available[-1]}") for alias, available in candidates), candidates[0][0], section="02/05  运行版本")
            available = dict(candidates)[args.inherit_from]
            options = tuple((module, f"复用至 {module}", f"从 M{int(module[1:]) + 1} 开始执行") for module in available[1:])
            args.inherit_through = panel.menu("选择复用终点", options, options[-1][0], section="02/05  运行版本")
        if status.is_file() and re.search(r",(not_run|failed)\b", status.read_text(encoding="utf-8-sig")):
            panel.menu("发现同名未完成记录", (
                ("resume", "续接已有运行", "使用该别名和现有回执"),
                ("cancel", "退出", "如需全新运行，请重新启动并输入新别名"),
            ), "resume", section="02/05  运行版本", check=confirm)

    def choose_data():
        products = params["products"]
        source_record = {}
        if args.inherit_from:
            source_path = ROOT / params["output"]["outputs"] / args.inherit_from / "protocol_freeze.json"
            try:
                source_record = json.loads(source_path.read_bytes())
            except (OSError, ValueError):
                raise ValueError("来源别名缺少有效的 M0 冻结记录。") from None
        source_product = source_record.get("product_combo", products["main"])
        args.product_combo = source_product if source_product in products["combinations"] else products["main"]
        if len(products["combinations"]) > 1:
            product_names = {"era5land": "ERA5-Land", "gldas21": "GLDAS-2.1 Noah", "chirps20": "CHIRPS v2.0"}
            options = []
            for key in products["combinations"]:
                land, precip = key.split("__")
                description = f"陆面 {product_names.get(land, land)} / 降水 {product_names.get(precip, precip)}"
                options.append((key, "主分析" if key == products["main"] else "稳健性复算", description))
            args.product_combo = panel.menu("选择陆面与降水来源", options, args.product_combo,
                                            section="03/05  数据与规范")
        variants = matrix["selectable_variants"]
        if len(variants) > 1:
            args.variant = panel.menu("选择分析方案（M0冻结与后续执行须一致）",
                                      variant_options(matrix), source_record.get("variant") if source_record.get("variant") in variants else variants[0],
                                      section="03/05  数据与规范")

    def choose_resources():
        args.progress = "auto"
        profile = panel.menu("选择本机运行档位", (
            ("auto", "自动", "根据可用内存限制进程和读盘并发"),
            ("low", "低占用", "最多 2 个工作进程、4 GiB 内存、1 路读取"),
            ("custom", "自定义", "输入三个资源上限"),
        ), "auto", section="04/05  资源与显示")
        args.runtime = {"profile": profile}
        if profile == "custom":
            def custom_resources(value):
                parts = (value or "").split()
                if len(parts) != 3 or not all(part.isdecimal() for part in parts):
                    raise ValueError("请输入三个以空格分隔的正整数。")
                request = dict(zip(("workers", "memory_gib", "io_workers"), map(int, parts)))
                request["profile"] = "custom"
                resolve_runtime(request)
                return request

            args.runtime = panel.ask("输入进程数、内存 GiB、读盘并发", custom_resources,
                                     section="04/05  资源与显示", hint="例如 4 6 2")

    def review():
        paths = []
        path_labels = {"interim": "中间数据", "frozen": "冻结交接", "outputs": "结果输出", "logs": "运行日志"}
        for name, directory in params["output"].items():
            root = ROOT / directory
            if name in {"interim", "frozen"}:
                root = root / "{数据名}"
            paths.append(f"{path_labels.get(name, name)}  {root / args.run_alias}")
        resources = resolve_runtime(args.runtime)
        selected = dag["targets"].get(args.modules[0], args.modules)
        ordered = plan_modules(dag, selected)
        run_logs = ROOT / params["output"]["logs"] / args.run_alias
        m0_audit = ordered == ["M0"]
        actions = (("start", "开始 M0 冻结前审计", "检查登记并写入独立审计日志"),
                   ("freeze", "正式冻结 M0", "审计通过后封存协议并登记运行编号")) if m0_audit else (
            ("start", "开始预检", "检查选项与依赖"),)
        if not m0_audit:
            if args.inherit_from:
                actions = (("execute", "冻结并开始接力", "校验来源后创建新身份并执行"),)
            elif (run_logs / "module_io_M0.json").is_file():
                actions = (("execute", "执行已选模块", "使用同一 M0 冻结别名"), *actions)
            else:
                actions = (("start", "开始预检", "此别名尚未正式冻结 M0。请先单独选择 M0 并正式冻结，再用同一别名执行"),)
        edits = tuple((f"edit{i}", f"修改{label}", "") for i, label in
                      enumerate(("运行范围", "运行版本", "数据与规范", "资源与显示"), 1))
        action = panel.menu("核对设置并确认", (*actions, *edits,
            ("cancel", "退出向导", "结束本次操作"),
        ), section="05/05  确认计划", check=confirm, details=(
            f"模块顺序  {' → '.join(ordered)}",
            f"上游来源  {args.inherit_from}（复用 M1–{args.inherit_through}）" if args.inherit_from else "上游来源  当前别名",
            f"运行版本  {args.run_alias}（{'全新' if args.new else '续接现有别名'}）",
            f"数据组合  {args.product_combo}    方案  {matrix.get('variant_labels', {}).get(args.variant, {}).get('label', args.variant)} ({args.variant})",
            *runtime_lines(resources),
            *paths,
        ))
        if action.startswith("edit"):
            return int(action[-1]) - 1
        args.dry_run = not m0_audit and action != "execute"
        args.freeze = action == "freeze"
        return None


    panel.navigation = True
    steps = (choose_scope, choose_version, choose_data, choose_resources, review)
    index, editing = 0, False
    while index < len(steps):
        try:
            revisit = steps[index]()
        except WizardBack:
            panel.rewind()
            index = 0
            editing = False
        else:
            if revisit is not None:
                index, editing = revisit, True
            elif editing:
                index, editing = len(steps) - 1, False
            else:
                index += 1
    return args


def confirm(value):
    """返回确认选项，选择退出时走统一中断清理。"""
    if value == "cancel":
        raise KeyboardInterrupt
    return value


def main(argv=None):
    """运行中文向导或高级入口，返回协议规定的进程退出码。"""
    from .runtime import memory_gib, resolve_runtime, runtime_lines
    from .progress import RunProgress
    from threading import Lock

    parser = ChineseParser(description="黄土高原 FD-WT 流水线", formatter_class=ChineseHelp, add_help=False)
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示此帮助")
    parser.add_argument("modules", metavar="模块", nargs="*", help="模块编号或 full／route1")
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG, help="协议参数文件")
    parser.add_argument("--run-alias", help="必填运行别名")
    parser.add_argument("--run-id", help="已计算的协议身份")
    parser.add_argument("--product-combo", help="已登记产品组合")
    parser.add_argument("--variant", default="lai_four_of_five", help="已放行规范变体")
    parser.add_argument("--new", action="store_true", help="选择全新运行")
    parser.add_argument("--dry-run", action="store_true", help="仅校验运行计划")
    parser.add_argument("--freeze", action="store_true", help="单独运行 M0 并正式冻结协议")
    parser.add_argument("--inherit-from", help="接力来源别名（创建新 M0 冻结后运行）")
    parser.add_argument("--inherit-through", choices=["M2", "M3", "M4", "M5", "M6"], default="M6", help="连续复用至指定上游模块")
    parser.add_argument("--progress", choices=["auto", "panel", "plain"], default="auto", help="进度显示模式")
    parser.add_argument("--runtime-profile", choices=["auto", "low", "custom"], default="auto", help="本机运行档位")
    parser.add_argument("--workers", type=int, help="自定义档工作进程上限")
    parser.add_argument("--memory-gib", type=int, help="自定义档内存预算 GiB")
    parser.add_argument("--io-workers", type=int, help="自定义档读盘并发上限")
    args = parser.parse_args(argv)
    interactive = not (sys.argv[1:] if argv is None else argv)
    try:
        if interactive:
            with WizardPanel("黄土高原 FD-WT · 运行向导") as panel:
                args = wizard(args, panel)
        elif not args.modules:
            raise ValueError("高级入口须指定模块或运行目标。")
        else:
            args.runtime = {"profile": args.runtime_profile, **{
                key: getattr(args, key) for key in ("workers", "memory_gib", "io_workers")
                if getattr(args, key) is not None
            }}
        meter = RunProgress()
        resources = resolve_runtime(args.runtime)
        effective = resources["effective"]
        validate_progress(parser, argparse.Namespace(progress=args.progress, dry_run=False))
        targets = args.modules[0] if len(args.modules) == 1 else args.modules
        last_summary = None
        summary_lock = Lock()

        def render():
            nonlocal last_summary
            snapshot = meter.snapshot()
            meter.observe(snapshot)
            event = snapshot["event"]
            key = (event.module, event.stage, event.state, event.operation, event.path, snapshot["terminal"])
            if status.panel.live is None:
                display_key = (key, int(snapshot["elapsed"] // 30))
            else:
                console = status.panel.live.console
                display_key = (key, int(snapshot["elapsed"]), event, status.view, console.width, console.height)
            with summary_lock:
                if last_summary == display_key:
                    return
                last_summary = display_key
            available = memory_gib()[1]
            statistics = f"{effective['workers']} 进程上限 · {effective['memory_gib']} GiB 预算"
            if available is not None:
                statistics += f" · 系统可用 {available:.2f} GiB"
            status.panel.draw_run(args.run_alias, snapshot, statistics, status.view)

        status = LiveStatus(args.progress, render)
        try:
            status.start()
            if status.panel.live is None:
                meter.on_stage_change = render
                sys.stderr.write("\n".join(runtime_lines(resources)) + "\n")
            if args.inherit_from and not args.dry_run:
                selected = plan_modules(load_config(ROOT / "workflow/dag.yaml"),
                    load_config(ROOT / "workflow/dag.yaml")["targets"].get(targets, [targets]) if isinstance(targets, str) else targets)
                end = int(args.inherit_through[1:])
                if selected != [f"M{i}" for i in range(len(selected))] or not 4 <= len(selected) <= 8 or end >= len(selected) - 1:
                    raise ValueError("接力执行目标须为继承终点之后的 M3–M7。")
                prepared = run_module("M0", args.config_path, args.run_id, args.run_alias, True,
                    product_combo=args.product_combo, variant=args.variant, freeze=True, progress=meter,
                    runtime=args.runtime, inherit_from=args.inherit_from, inherit_through=args.inherit_through)
                if not prepared.get("m0_audit", {}).get("formal_freeze_written"):
                    raise ValueError("M0 冻结未放行，未执行接力。")
                args.new = False
            plan = run_module(targets, args.config_path, args.run_id, args.run_alias,
                              not args.new, product_combo=args.product_combo,
                              variant=args.variant, dry_run=args.dry_run, freeze=args.freeze,
                              progress=meter, runtime=args.runtime)
            outcomes = plan.get("module_status", {})
            failed = (plan.get("m0_audit", {}).get("status") == "failed"
                      or any(value == "failed" or (value == "exited" and module != "M8")
                             for module, value in outcomes.items()))
            meter.finish("failed" if failed else "passed")
            try:
                meter.save_history()
            except OSError as error:
                sys.stderr.write(f"计时日志未保存：{error}\n")
        except (KeyboardInterrupt, EOFError):
            meter.finish("interrupted")
            raise
        except Exception:
            meter.finish("failed")
            raise
        finally:
            status.close()
            render()
        report = plan.get("m0_audit")
        stages = plan.get("module_status")
        if stages is not None and not (interactive and sys.stdout.isatty()):
            for stage, outcome in stages.items():
                sys.stderr.write(f"{stage} 状态 {outcome}\n")
            sys.stderr.write(f"M1 报告位于 {plan['m1_reports']}\n")
        elif stages is None and report is None:
            sys.stderr.write(f"计划预检完成，共 {len(plan['modules'])} 个模块。\n")
        elif report is not None:
            sys.stderr.write(f"M0 冻结前审计完成，日志位于 {plan['audit_log']}\n")
            if report["formal_freeze_written"]:
                sys.stderr.write(f"M0 正式冻结完成，运行编号 {plan['run_id']}\n")
            for check in report["checks"]:
                if check["status"] != "passed":
                    sys.stderr.write(f"  [{check['status']}] {check['detail']}\n")
        if interactive and sys.stdout.isatty():
            sys.stderr.write(f"\n运行摘要 · {plan['run_alias']}\n")
            sys.stderr.write(f"  结果：{'失败' if failed else '完成'}\n")
            if stages:
                from .progress import LABELS
                for stage, outcome in stages.items():
                    sys.stderr.write(f"  {stage}  {LABELS.get(outcome, outcome)}\n")
            for key, label in (("downstream", "冻结交接"), ("m1_reports", "审计报告"), ("audit_log", "审计日志")):
                if plan.get(key):
                    sys.stderr.write(f"  {label}：{plan[key]}\n")
        else:
            sys.stdout.write(json.dumps(plan, ensure_ascii=False) + "\n")
        if stages is not None and any(outcome == "failed" or (outcome == "exited" and stage != "M8")
                                      for stage, outcome in stages.items()):
            return 1
        return 2 if report and report["status"] == "failed" else 0
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write("运行已中断。\n")
        return 130
    except (ValueError, KeyError, yaml.YAMLError) as error:
        sys.stderr.write(f"预检失败：{error}\n")
        return 2
    except Exception as error:
        sys.stderr.write(f"执行失败：{error}\n")
        return 1


if __name__ == "__main__":
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
