"""脚本名：scr_remove_run.py（MX · 分析枝干清理）
功能简介：预览精确运行别名的产物，确认后移入 Windows 回收站。
作者：Codex
版本：v0.1.0
读取数据：项目产物目录和运行索引。
生成数据：更新运行索引，已确认产物移入系统回收站。
其他文件：复用统一运行入口的别名锁和索引锁。
运行示例：python -m src.MX.scr_remove_run
退出码：0 完成或取消，1 失败，130 中断。
"""
from contextlib import ExitStack, suppress
import csv
from dataclasses import dataclass
import os
from pathlib import Path
import stat
import sys

from workflow.freeze_m0 import alias_lock, atomic_write, index_lock
from workflow.run_era5land import csv_bytes
from workflow.run_module import ROOT, validate_alias

INDEX = Path("metadata/run_index.csv")
OUTPUTS = {"outputs_path": Path("outputs"), "logs_path": Path("logs")}
DATA = {"interim_root": Path("data/interim"), "frozen_root": Path("data/frozen")}


@dataclass(frozen=True)
class CleanupPlan:
    """确认页所绑定的登记和目录身份。"""

    alias: str
    registration: tuple
    directories: tuple

    @property
    def paths(self):
        """按预览顺序返回绝对目录路径。"""
        return tuple(path for path, _, _ in self.directories)


def plain_stat(path):
    """读取文件身份，拒绝 Windows 重解析点和其他平台的符号链接。"""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError(f"路径含符号链接或目录联接：{path}")
    return info


def checked_path(root, path, *, missing=False):
    """从项目根逐层检查路径，拒绝越界和目录联接。"""
    relative = path.relative_to(root)
    if not relative.parts or ".." in relative.parts:
        raise ValueError(f"路径越过项目目录：{path}")
    for i in range(1, len(relative.parts) + 1):
        try:
            info = plain_stat(root.joinpath(*relative.parts[:i]))
        except FileNotFoundError:
            if missing:
                return None
            raise
        if i < len(relative.parts) and not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"路径的上级不是目录：{path}")
    return info


def read_index(root):
    """读取索引并保留原表头及其他别名的全部字段。"""
    path = root / INDEX
    info = checked_path(root, path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("运行索引不是普通文件。")
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        columns = reader.fieldnames
        required = {"run_alias", "run_id", *OUTPUTS, *DATA}
        if not columns or not required <= set(columns) or len(columns) != len(set(columns)):
            raise ValueError("运行索引表头无效。")
        rows = list(reader)
    if any(None in row or None in row.values() for row in rows):
        raise ValueError("运行索引存在列数异常的登记。")
    return columns, rows


def find_registration(rows, alias):
    """按精确别名定位登记，并拒绝 Windows 下可能冲突的大小写变体。"""
    same = [row for row in rows if row["run_alias"].casefold() == alias.casefold()]
    if same and (len(same) != 1 or same[0]["run_alias"] != alias):
        raise ValueError("别名大小写不一致或存在重复登记，请核对运行索引。")
    return same[0] if same else {}


def list_runs(root):
    """列出正式登记和标准产物目录中的试跑，按别名去重。"""
    _, rows = read_index(root)
    runs = {row["run_alias"]: row["run_id"] for row in rows}

    def children(parent):
        info = checked_path(root, parent, missing=True)
        return parent.iterdir() if info and stat.S_ISDIR(info.st_mode) else ()

    def discover(parent):
        for path in children(parent):
            try:
                validate_alias(path.name)
            except ValueError:
                continue
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
                runs.setdefault(path.name, "")

    for base in OUTPUTS.values():
        discover(root / base)
    for base in DATA.values():
        for dataset in children(root / base):
            info = dataset.lstat()
            if stat.S_ISDIR(info.st_mode) and not (
                    getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                discover(dataset)
    return sorted(runs.items(), reverse=True)


def indexed_path(root, value, base, alias=None):
    """约束索引路径在指定产物根内，运行目录末级必须为精确别名。"""
    relative = Path(value)
    if relative.anchor or ".." in relative.parts or not relative.is_relative_to(base):
        raise ValueError(f"登记路径越过 {base}：{value}")
    if alias is not None and (relative == base or relative.name != alias):
        raise ValueError(f"登记路径不是独占的别名目录：{value}")
    result = root / relative
    checked_path(root, result, missing=True)
    return result


def validate_tree(path):
    """检查待清理目录内的每个条目，阻止递归回收链接。"""
    with os.scandir(path) as entries:
        for entry in entries:
            child = Path(entry.path)
            info = plain_stat(child)
            if stat.S_ISDIR(info.st_mode):
                validate_tree(child)
            elif not stat.S_ISREG(info.st_mode):
                raise ValueError(f"产物含不支持的文件类型：{child}")


def preview(root, alias):
    """列出运行别名的已登记和未登记产物，进行只读校验。"""
    validate_alias(alias)
    _, rows = read_index(root)
    row = find_registration(rows, alias)
    candidates = set()

    def add(parent):
        parent_info = checked_path(root, parent, missing=True)
        if parent_info is None:
            return
        if not stat.S_ISDIR(parent_info.st_mode):
            raise ValueError(f"产物上级不是目录：{parent}")
        matches = [child for child in parent.iterdir() if child.name.casefold() == alias.casefold()]
        if any(child.name != alias for child in matches):
            raise ValueError(f"目录别名大小写不一致：{parent / alias}")
        candidates.update(matches)

    for field, base in OUTPUTS.items():
        add(root / base)
        if row:
            add(indexed_path(root, row[field], base, alias).parent)
    for field, base in DATA.items():
        bases = {root / base}
        if row:
            bases.add(indexed_path(root, row[field], base))
        for data_root in bases:
            info = checked_path(root, data_root, missing=True)
            if info is None:
                continue
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError(f"数据根不是目录：{data_root}")
            for dataset in data_root.iterdir():
                if dataset.is_dir():
                    add(dataset)

    for other in rows:
        if other == row:
            continue
        for field in (*OUTPUTS, *DATA):
            other_path = (root / other[field]).resolve()
            if any(other_path == path or other_path.is_relative_to(path) for path in candidates):
                raise ValueError(f"清理范围与其他运行登记冲突：{other['run_alias']}")

    directories = []
    for path in sorted(candidates):
        info = checked_path(root, path)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"别名对应的产物不是目录：{path}")
        if any(parent in candidates for parent in path.parents):
            raise ValueError(f"清理目录相互嵌套：{path}")
        validate_tree(path)
        directories.append((path, info.st_dev, info.st_ino))
    return CleanupPlan(alias, tuple(row.items()), tuple(directories))


def recycle_directory(path):
    """调用 Windows IFileOperation，按绝对路径执行回收站操作。"""
    if os.name != "nt":
        raise OSError("当前平台不支持 Windows 回收站。")
    import ctypes as c
    from ctypes import wintypes as w
    from uuid import UUID

    def guid(value):
        return (c.c_ubyte * 16).from_buffer_copy(UUID(value).bytes_le)

    def method(obj, slot, result, *types):
        vtable = c.cast(obj, c.POINTER(c.POINTER(c.c_void_p)))[0]
        return c.WINFUNCTYPE(result, c.c_void_p, *types)(vtable[slot])

    def check(result):
        if result < 0:
            raise OSError(f"Windows 回收站操作失败（0x{result & 0xffffffff:08X}）。")

    # COM 接口槽号与操作标志取自 Windows SDK。
    ole = c.OleDLL("ole32")
    shell = c.OleDLL("shell32")
    operation, item = c.c_void_p(), c.c_void_p()
    check(ole.CoInitializeEx(None, 2))
    try:
        clsid = guid("3ad05575-8857-4850-9277-11b85bdb8e09")
        iid = guid("947aab5f-0a5c-4c13-b4d6-4bf7836fc9f8")
        check(ole.CoCreateInstance(c.byref(clsid), None, 1, c.byref(iid), c.byref(operation)))
        item_iid = guid("43826d1e-e718-42ee-bc55-a1e261c37bfe")
        check(shell.SHCreateItemFromParsingName(w.LPCWSTR(str(path)), None, c.byref(item_iid), c.byref(item)))
        flags = 0x00080000 | 0x4000 | 0x0400 | 0x00100000 | 0x0004
        check(method(operation, 5, c.c_long, w.DWORD)(operation, flags))
        check(method(operation, 18, c.c_long, c.c_void_p, c.c_void_p)(operation, item, None))
        check(method(operation, 21, c.c_long)(operation))
        aborted = w.BOOL()
        check(method(operation, 22, c.c_long, c.POINTER(w.BOOL))(operation, c.byref(aborted)))
        if aborted.value or path.exists():
            raise OSError(f"Windows 未完成回收：{path}")
    finally:
        for obj in (item, operation):
            if obj:
                method(obj, 2, w.ULONG)(obj)
        ole.CoUninitialize()


def cleanup(root, plan, recycle=recycle_directory):
    """锁定别名、复核预览、回收目录，全部成功后移除索引行。"""
    checked_path(root, root / "logs/.run_locks", missing=True)
    with ExitStack() as stack:
        try:
            stack.enter_context(alias_lock(root, plan.alias))
        except OSError as error:
            raise ValueError(f"该别名正在运行或清理，或无法获取锁：{plan.alias}") from error
        if preview(root, plan.alias) != plan:
            raise ValueError("清理范围已变化，请重新预览并确认。")
        try:
            for path, device, inode in plan.directories:
                info = checked_path(root, path)
                if (info.st_dev, info.st_ino) != (device, inode):
                    raise ValueError(f"目录身份已变化：{path}")
                validate_tree(path)
                recycle(path)
                if path.exists():
                    raise OSError(f"回收后目录仍存在：{path}")
            if plan.registration:
                lock = root / "logs/.run_index.lock"
                checked_path(root, lock, missing=True)
                with index_lock(lock):
                    columns, rows = read_index(root)
                    row = find_registration(rows, plan.alias)
                    if tuple(row.items()) != plan.registration:
                        raise ValueError("运行登记在清理期间发生变化。")
                    atomic_write(root / INDEX, csv_bytes(columns, [item for item in rows if item != row]),
                                 replace=True)
        except (OSError, ValueError, KeyboardInterrupt) as error:
            removed = "、".join(str(path) for path in plan.paths if not path.exists()) or "无"
            remaining = "、".join(str(path) for path in plan.paths if path.exists()) or "无"
            raise OSError(f"清理中止，运行登记保留。已移除：{removed}。仍在项目中：{remaining}。{error}") from error


def recycle_selected(root, aliases, confirm, recycle=recycle_directory):
    """预览整批所选枝干，明确确认后逐项清理并汇总结果。"""
    plans = [preview(root, alias) for alias in aliases]
    missing = [plan.alias for plan in plans if not plan.paths and not plan.registration]
    if missing:
        raise ValueError(f"以下枝干已不存在，请刷新后重选：{'、'.join(missing)}")
    if not plans or not confirm(plans):
        return None
    results = []
    for plan in plans:
        try:
            cleanup(root, plan, recycle)
        except (OSError, ValueError, csv.Error) as error:
            results.append((plan.alias, str(error)))
        else:
            results.append((plan.alias, ""))
    return results


def show_panel(root):
    """显示可勾选的枝干列表及独立的确认窗口。"""
    import tkinter as tk
    from tkinter import messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    window = tk.Tk()
    window.title("MX · 清理分析枝干")
    window.geometry("780x450")
    window.minsize(560, 300)
    frame = ttk.Frame(window, padding=16)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="勾选一个或多个分析枝干，再点击「确定」。").pack(anchor="w", pady=(0, 10))
    listing = ttk.Frame(frame)
    listing.pack(fill="both", expand=True)
    tree = ttk.Treeview(listing, columns=("checked", "alias", "run_id"), show="headings", selectmode="browse")
    for column, title, width in (("checked", "勾选", 55), ("alias", "运行别名", 255), ("run_id", "运行编号", 400)):
        tree.heading(column, text=title)
        tree.column(column, width=width, stretch=column != "checked",
                    anchor="center" if column == "checked" else "w")
    bar = ttk.Scrollbar(listing, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    footer = ttk.Frame(frame)
    footer.pack(fill="x", pady=(12, 0))
    status = ttk.Label(footer)
    status.pack(side="left")
    checked = set()
    aliases = {}

    def update_count():
        status.configure(text=f"已勾选 {len(checked)} 项，共 {len(aliases)} 项" if aliases else "暂无分析枝干")
        proceed.configure(state="normal" if checked else "disabled")

    def refresh():
        runs = list_runs(root)
        tree.delete(*tree.get_children())
        checked.clear()
        aliases.clear()
        for alias, run_id in runs:
            item = tree.insert("", "end", values=("☐", alias, run_id or "未登记"))
            aliases[item] = alias
        update_count()

    def toggle(item):
        if item in aliases:
            if item in checked:
                checked.remove(item)
            else:
                checked.add(item)
            tree.set(item, "checked", "☑" if item in checked else "☐")
            update_count()

    def confirm(plans):
        dialog = tk.Toplevel(window)
        dialog.title("确认清理")
        dialog.transient(window)
        dialog.geometry("700x420")
        ttk.Label(dialog, text=f"即将清理 {len(plans)} 个枝干。请核对目录和运行索引。").pack(
            anchor="w", padx=12, pady=10)
        details = ScrolledText(dialog, wrap="word", height=12)
        details.pack(fill="both", expand=True, padx=12)
        for plan in plans:
            details.insert("end", f"{plan.alias}\n")
            for path in plan.paths:
                details.insert("end", f"  {path}\n")
            details.insert("end", "  移除运行索引行\n\n" if plan.registration else "  未登记索引\n\n")
        details.configure(state="disabled")
        buttons = ttk.Frame(dialog, padding=12)
        buttons.pack(fill="x")
        confirmed = False

        def accept():
            nonlocal confirmed
            confirmed = True
            dialog.destroy()

        ttk.Button(buttons, text="移入回收站", command=accept).pack(side="right", padx=(8, 0))
        cancel = ttk.Button(buttons, text="取消", command=dialog.destroy)
        cancel.pack(side="right")
        dialog.bind("<Escape>", lambda _: dialog.destroy())
        dialog.grab_set()
        cancel.focus_set()
        window.wait_window(dialog)
        return confirmed

    def submit():
        selected = [aliases[item] for item in tree.get_children() if item in checked]
        try:
            results = recycle_selected(root, selected, confirm)
            if results is None:
                return
            refresh()
        except (OSError, ValueError, csv.Error) as error:
            messagebox.showerror("无法清理", str(error), parent=window)
            return
        failures = [f"{alias}：{error}" for alias, error in results if error]
        summary = f"已清理 {len(results) - len(failures)} 项。"
        if failures:
            messagebox.showwarning("清理结果", "\n".join([summary, *failures]), parent=window)
        else:
            messagebox.showinfo("清理完成", summary, parent=window)

    proceed = ttk.Button(footer, text="确定", command=submit)
    proceed.pack(side="right")
    ttk.Button(footer, text="关闭", command=window.destroy).pack(side="right", padx=8)
    ttk.Button(footer, text="刷新", command=refresh).pack(side="right")
    tree.bind("<ButtonRelease-1>", lambda event: toggle(tree.identify_row(event.y)))
    tree.bind("<space>", lambda _: toggle(tree.focus()))
    try:
        refresh()
        window.mainloop()
    finally:
        with suppress(tk.TclError):
            window.destroy()


def main():
    """从项目根启动桌面清理面板。"""
    from tkinter import TclError

    try:
        show_panel(ROOT)
        return 0
    except (KeyboardInterrupt, EOFError):
        sys.stderr.write("已取消清理。\n")
        return 130
    except (OSError, ValueError, csv.Error, TclError) as error:
        sys.stderr.write(f"清理失败：{error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
