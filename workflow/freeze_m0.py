"""脚本名：freeze_m0.py（编排层 · M0 运行登记）

功能简介：封存已通过审计的协议，建立可续跑的运行索引。
作者：Codex
版本：v0.1.0
读取数据：统一入口提供的审计和输入快照、Git 工作树、运行索引。
生成数据：运行身份、协议冻结记录、模块回执、状态和运行索引。
其他文件：索引锁位于 logs。
运行示例：python -m workflow.run_module M0 --run-alias 2026-11-10_M0冻结 --freeze
退出码：由统一入口定义。
"""

from contextlib import contextmanager
import csv
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
from tempfile import NamedTemporaryFile


def json_bytes(value):
    """按确定性顺序编码冻结记录。"""
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def atomic_write(path, content, *, replace=False):
    """原子发布文件，续跑仅接受字节完全相同的既有产物。"""
    if path.exists() and not replace:
        if path.read_bytes() != content:
            raise ValueError(f"冻结文件内容不同，请使用新别名：{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def index_lock(path, *, blocking=True):
    """跨进程序列化登记，系统在进程退出时释放锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield


def alias_lock(root, alias):
    """使用独立于产物目录的锁，协调同一别名的执行和清理。"""
    key = sha256(alias.casefold().encode("utf-8")).hexdigest()
    return index_lock(root / "logs" / ".run_locks" / f"{key}.lock", blocking=False)


def register_freeze(root, plan, params, report, inputs, build_run_id, modules):
    """冻结协议输入和代码身份，索引最后发布以支持失败后重试。"""
    checks = {row["check_id"]: row["status"] for row in report["checks"]}
    if report["status"] == "failed" or any(
        checks[key] != "passed" for key in ("research_boundary", "random_seed", "specification_enumeration")
    ):
        raise ValueError("M0 冻结条件未满足，请查看审计日志。")
    # M1 的可变验收清单独立登记，避免验收进展改写 M0 协议身份。
    m1_inputs = {"metadata/source_file_manifest.csv", "metadata/source_variable_map.csv",
                 "metadata/site_boundary_acceptance.csv"}
    snapshot = {path: content.decode("utf-8") for path, content in inputs.items() if path not in m1_inputs}
    input_hashes = {path: report["input_sha256"][path] for path in snapshot}
    params_hash = sha256(json_bytes({"inputs": input_hashes, "product_combo": plan["product_combo"],
                                    "variant": plan["variant"]})).hexdigest()
    code_paths = sorted(path for directory in ("src", "workflow")
                        for path in (root / directory).rglob("*.py"))
    code_snapshot = {path.relative_to(root).as_posix(): path.read_bytes().decode("utf-8")
                     for path in code_paths}
    code_files = {path: sha256(source.encode("utf-8")).hexdigest()
                  for path, source in code_snapshot.items()}
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    code_hash = sha256(json_bytes({"files": code_files, "git_commit": commit})).hexdigest()
    run_id = build_run_id(params, params_hash, code_hash)
    if plan["run_id"] not in (None, run_id):
        raise ValueError("指定的 run_id 与当前参数和代码哈希不一致。")

    alias = plan["run_alias"]
    roots = {name: (root / params["output"][name]).resolve()
             for name in ("interim", "frozen", "outputs", "logs")}
    expected_roots = {"interim": "data/interim", "frozen": "data/frozen",
                      "outputs": "outputs", "logs": "logs"}
    if any(not path.is_relative_to(root / expected_roots[name]) for name, path in roots.items()):
        raise ValueError("冻结路径须位于项目登记的输出目录内。")
    output, logs = ((roots[name] / alias).resolve() for name in ("outputs", "logs"))
    if output.parent != roots["outputs"] or logs.parent != roots["logs"]:
        raise ValueError("运行别名不能指向其他输出目录。")
    relative = lambda path: path.relative_to(root).as_posix()
    index_path = root / "metadata/run_index.csv"
    identity = {
        "run_alias": alias, "run_id": run_id, "module": "M0", "status": "passed",
        "protocol_version": report["protocol_version"], "params_hash": params_hash,
        "code_hash": code_hash, "git_commit": commit, "random_seed": params["random"],
        "product_combo": plan["product_combo"], "variant": plan["variant"],
    }
    record = {**identity, "registration": report["registration"], "regional_release": False,
              "input_sha256": input_hashes, "input_snapshot": snapshot,
              "code_files": code_files, "code_snapshot": code_snapshot}
    protocol_path = output / "protocol_freeze.json"
    index_row = {"run_alias": alias, "run_id": run_id, "interim_root": relative(roots["interim"]),
                 "frozen_root": relative(roots["frozen"]), "outputs_path": relative(output),
                 "logs_path": relative(logs)}
    status = "module_id,status\n" + "".join(
        f"{module},{'passed' if module == 'M0' else 'not_run'}\n"
        for module in modules
    )
    receipt = {
        "module_id": "M0", "run_id": run_id, "status": "passed", "params_hash": params_hash,
        "code_hash": code_hash, "random_seed_id": params["random"]["seed_id"],
        "input_files": [{"path": path, "sha256": digest} for path, digest in input_hashes.items()],
        "output_files": [{"path": relative(protocol_path), "sha256": sha256(json_bytes(record)).hexdigest()}],
    }
    with index_lock(root / "logs" / ".run_index.lock"):
        index = csv.DictReader(StringIO(index_path.read_text(encoding="utf-8-sig")))
        if index.fieldnames != list(index_row):
            raise ValueError("运行索引表头与登记契约不一致。")
        rows = list(index)
        matched = [row for row in rows if row["run_alias"].casefold() == alias.casefold()]
        if matched and (matched != [index_row] or not plan["resume"]):
            raise ValueError("运行别名已登记，请使用新别名。")
        if output.exists() and (not plan["resume"] or (any(output.iterdir()) and not protocol_path.is_file())):
            raise ValueError("运行输出目录已存在，请使用新别名。")
        atomic_write(protocol_path, json_bytes(record))
        atomic_write(output / "run.json", json_bytes(identity))
        atomic_write(logs / "run.json", json_bytes(identity))
        atomic_write(logs / "deviation_log.csv", inputs["config/deviation_log.csv"])
        atomic_write(logs / "module_status.csv", status.encode("utf-8"))
        atomic_write(logs / "module_io_M0.json", json_bytes(receipt))
        if not matched:
            buffer = StringIO(newline="")
            writer = csv.DictWriter(buffer, fieldnames=list(index_row), lineterminator="\n")
            writer.writeheader()
            writer.writerows([*rows, index_row])
            atomic_write(index_path, buffer.getvalue().encode("utf-8"), replace=True)
    return {**plan, "run_id": run_id, "freeze_record": str(protocol_path),
            "m0_audit": {**report, "formal_freeze_written": True}}
