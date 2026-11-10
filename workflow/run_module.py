"""脚本名：run_module.py（编排层 · 统一运行入口）

功能简介：收集运行控制信息并在科学任务启动前验证运行计划。
作者：Codex
版本：v0.1.0
读取数据：config 下的参数与规范矩阵、workflow/dag.yaml、logs 下的运行登记。
生成数据：无。架构阶段仅支持计划预检。
其他文件：进度和错误发送到标准错误。
运行示例：python -m workflow.run_module
退出码：0 计划有效，1 执行失败，2 预检失败，130 中断。
"""
import argparse
from datetime import date
import json
from pathlib import Path
import re
import sys
from time import monotonic

import yaml

from .terminal_panel import ChineseHelp, ChineseParser, LiveStatus, WizardPanel, check_progress, validate_progress


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "params.yaml"


def load_config(path):
    """读取 UTF-8 YAML 映射。返回配置字典，不补写科学参数。"""
    with Path(path).open(encoding="utf-8-sig") as source:
        config = yaml.safe_load(source)
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


def run_module(module_id, config_path=DEFAULT_CONFIG, run_id=None, run_alias=None,
               resume=True, overwrite_frozen=False, *, product_combo=None,
               variant="main", dry_run=False):
    """预检统一入口。返回有序模块和运行控制信息，不写科学数据。"""
    alias = validate_alias(run_alias)
    if overwrite_frozen:
        raise ValueError("冻结产物禁止覆盖。")
    params = load_config(config_path)
    matrix = load_config(ROOT / "config" / "specification_matrix.yaml")
    dag = load_config(ROOT / "workflow" / "dag.yaml")
    targets = dag["targets"].get(module_id, [module_id]) if isinstance(module_id, str) else module_id
    modules = plan_modules(dag, targets)
    product = product_combo or params["products"]["main"]
    if product not in params["products"]["combinations"]:
        raise ValueError("产品组合尚未登记。")
    if variant not in matrix["selectable_variants"]:
        raise ValueError("规范变体尚未放行。")
    plan = {"modules": modules, "run_alias": alias, "run_id": run_id,
            "product_combo": product, "variant": variant, "resume": resume}
    if dry_run:
        return plan
    raise ValueError("科学模块尚未接入生产入口。请使用计划预检查看编排顺序。")


def wizard(args, panel):
    """按中文问答收集与高级入口共用的控制信息。"""
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

    target = panel.menu("选择要预检的范围", (
        ("route1", "路线一主分析", "M0–M7、M9–M10"),
        ("full", "完整工作流", "M0–M10，包含 M8 路线二"),
        ("custom", "指定模块", "选择一个或多个模块，自动纳入必需的上游依赖"),
    ), "full", section="01  运行范围")
    args.modules = [target]
    if target == "custom":
        args.modules = panel.ask("输入模块编号", scope, section="01  运行范围",
                                 details=names, hint="例如 M4, M6，可用空格或中英文逗号分隔")
    args.run_alias = panel.ask("输入运行别名", validate_alias, section="02  运行版本",
                               hint="格式 YYYY-MM-DD_短描述，例如 2026-11-10_主分析")
    paths = []
    path_labels = {"interim": "中间数据", "frozen": "冻结交接", "outputs": "结果输出", "logs": "运行日志"}
    for name, directory in params["output"].items():
        root = ROOT / directory
        if name in {"interim", "frozen"}:
            root = root / "{数据名}"
        paths.append(f"{path_labels.get(name, name)}  {root / args.run_alias}")
    status = ROOT / params["output"]["logs"] / args.run_alias / "module_status.csv"
    if status.is_file() and re.search(r",(not_run|failed)\b", status.read_text(encoding="utf-8-sig")):
        panel.menu("发现同名未完成记录", (
            ("resume", "预检续跑计划", "以该别名作为续跑目标"),
            ("cancel", "退出", "如需全新运行，请重新启动并输入新别名"),
        ), "resume", section="02  运行版本", check=confirm)
    else:
        args.new = not status.is_file()
    products = params["products"]
    args.product_combo = products["main"]
    if len(products["combinations"]) > 1:
        product_names = {"era5land": "ERA5-Land", "gldas21": "GLDAS-2.1 Noah", "chirps20": "CHIRPS v2.0"}
        options = []
        for key in products["combinations"]:
            land, precip = key.split("__")
            description = f"陆面 {product_names.get(land, land)} / 降水 {product_names.get(precip, precip)}"
            options.append((key, "主分析" if key == products["main"] else "稳健性复算", description))
        args.product_combo = panel.menu("选择陆面与降水来源", options, products["main"],
                                        section="03  数据与规范")
    variants = matrix["selectable_variants"]
    if len(variants) > 1:
        args.variant = panel.menu("选择已放行的规范变体",
                                  [(key, key, "") for key in variants], variants[0],
                                  section="03  数据与规范")
    args.progress = panel.menu("选择运行阶段的进度显示", (
        ("auto", "自动切换", "支持光标更新时显示彩色面板，重定向时使用文本"),
        ("panel", "彩色实时面板", "要求终端支持光标更新"),
        ("plain", "逐行文本", "适用于管道、日志收集和 CI"),
    ), "auto", section="04  显示方式", check=check_progress)
    selected = dag["targets"].get(target, args.modules)
    ordered = plan_modules(dag, selected)
    panel.menu("核对设置后开始计划预检", (
        ("start", "开始预检", "检查选项与依赖，当前不会生成科学产物"),
        ("cancel", "退出向导", "结束本次预检"),
    ), section="05  确认计划", check=confirm, details=(
        f"模块顺序  {' → '.join(ordered)}",
        f"运行版本  {args.run_alias}（{'全新' if args.new else '按现有别名预检'}）",
        f"数据组合  {args.product_combo}    规范  {args.variant}",
        *paths,
    ))
    args.dry_run = True
    return args


def confirm(value):
    """返回确认选项，选择退出时走统一中断清理。"""
    if value == "cancel":
        raise KeyboardInterrupt
    return value


def main(argv=None):
    """运行中文向导或高级入口，返回协议规定的进程退出码。"""
    parser = ChineseParser(description="黄土高原 FD-WT 流水线", formatter_class=ChineseHelp, add_help=False)
    parser._positionals.title = "位置参数"
    parser._optionals.title = "选项"
    parser.add_argument("-h", "--help", action="help", help="显示此帮助")
    parser.add_argument("modules", metavar="模块", nargs="*", help="模块编号或 full／route1")
    parser.add_argument("--config-path", type=Path, default=DEFAULT_CONFIG, help="协议参数文件")
    parser.add_argument("--run-alias", help="必填运行别名")
    parser.add_argument("--run-id", help="已计算的协议身份")
    parser.add_argument("--product-combo", help="已登记产品组合")
    parser.add_argument("--variant", default="main", help="已放行规范变体")
    parser.add_argument("--new", action="store_true", help="选择全新运行")
    parser.add_argument("--dry-run", action="store_true", help="仅校验运行计划")
    parser.add_argument("--progress", choices=["auto", "panel", "plain"], default="auto", help="进度显示模式")
    args = parser.parse_args(argv)
    interactive = not (sys.argv[1:] if argv is None else argv)
    started = monotonic()
    try:
        if interactive:
            with WizardPanel("黄土高原 FD-WT · 运行向导") as panel:
                args = wizard(args, panel)
        elif not args.modules:
            raise ValueError("高级入口须指定模块或运行目标。")
        validate_progress(parser, argparse.Namespace(progress=args.progress, dry_run=False))
        targets = args.modules[0] if len(args.modules) == 1 else args.modules
        def render():
            status.panel.draw("黄土高原 FD-WT", args.run_alias, "正在预检",
                              "核对依赖和运行选项", "目标 " + "、".join(args.modules),
                              f"耗时 {monotonic() - started:.2f} 秒", 0.0)

        status = LiveStatus(args.progress, render)
        try:
            status.start()
            plan = run_module(targets, args.config_path, args.run_id, args.run_alias,
                              not args.new, product_combo=args.product_combo,
                              variant=args.variant, dry_run=args.dry_run)
        finally:
            status.close()
        sys.stderr.write(f"计划预检完成，共 {len(plan['modules'])} 个模块。科学模块待接入。\n")
        sys.stdout.write(json.dumps(plan, ensure_ascii=False) + "\n")
        return 0
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
