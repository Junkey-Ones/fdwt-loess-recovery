"""统一入口的本机资源探测、运行档位和有界任务队列。"""
from collections import deque
from concurrent.futures import ProcessPoolExecutor
import ctypes
import multiprocessing
import os
from threading import Lock


_spawn_lock = Lock()
_thread_variables = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                     "NUMEXPR_NUM_THREADS", "ARROW_NUM_THREADS")


def memory_gib():
    """返回物理总内存及当前可用内存，探测失败时返回空值。"""
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_uint32), ("load", ctypes.c_uint32),
                        ("total", ctypes.c_uint64), ("available", ctypes.c_uint64),
                        ("rest", ctypes.c_uint64 * 5)]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.total / 2**30, status.available / 2**30
    elif hasattr(os, "sysconf"):
        try:
            page = os.sysconf("SC_PAGE_SIZE")
            return tuple(os.sysconf(key) * page / 2**30
                         for key in ("SC_PHYS_PAGES", "SC_AVPHYS_PAGES"))
        except (OSError, ValueError):
            pass
    return None, None


def resolve_runtime(request=None):
    """校验运行档位，记录请求、生效上限及探测值。"""
    if request is not None and not isinstance(request, dict):
        raise ValueError("运行资源配置须为映射。")
    request = dict(request or {})
    allowed = {"profile", "workers", "memory_gib", "io_workers"}
    if request.keys() - allowed:
        raise ValueError("运行资源配置含未知字段。")
    profile = request.get("profile", "auto")
    defaults = {"auto": (6, 12, 2), "low": (2, 4, 1)}
    keys = ("workers", "memory_gib", "io_workers")
    if not isinstance(profile, str):
        raise ValueError("运行档位须为文本。")
    if profile == "custom":
        values = tuple(request.get(key) for key in keys)
        if any(type(value) is not int or value < 1 for value in values):
            raise ValueError("自定义档须提供正整数进程数、内存 GiB 和读盘并发。")
    elif profile in defaults and set(request) <= {"profile"}:
        values = defaults[profile]
    else:
        raise ValueError("请选择有效档位。资源上限仅在自定义档设置。")
    workers, budget, io_workers = values
    cpu = (getattr(os, "process_cpu_count", os.cpu_count)() or 1)
    total, available = memory_gib()
    if profile == "custom" and (workers > min(cpu, 61) or io_workers > workers
                                or (total is not None and budget > total)):
        raise ValueError("自定义资源超过逻辑处理器、物理内存或工作进程上限。")
    memory = min(budget, max(0.0, available - 1)) if available is not None else min(budget, 4)
    effective_workers = max(1, min(workers, cpu, 61, int(memory / 0.75)))
    effective = dict(workers=effective_workers, memory_gib=round(memory, 2),
                     io_workers=min(io_workers, effective_workers))
    requested = dict(zip(keys, values))
    reasons = [f"{label}按本机可用资源下调" for key, label in
               zip(keys, ("工作进程数", "内存预算", "读盘并发"))
               if effective[key] < requested[key]]
    return dict(profile=profile, requested=requested, effective=effective, reasons=reasons,
                hardware=dict(logical_cpu=cpu, total_memory_gib=total, available_memory_gib=available))


def runtime_lines(runtime):
    """构造确认页的资源摘要。"""
    hardware = runtime["hardware"]
    total = hardware["total_memory_gib"]
    lines = [f"硬件  {hardware['logical_cpu']} 个逻辑处理器  "
             + (f"物理内存 {total:.2f} GiB" if total is not None else "物理内存探测不可用")]
    for key, label in (("requested", "请求上限"), ("effective", "生效上限")):
        value = runtime[key]
        lines.append(f"{label}  {value['workers']} 进程  "
                     f"{value['memory_gib']} GiB  {value['io_workers']} 路读取")
    return (*lines, *runtime["reasons"])


def ordered_tasks(function, tasks, runtime, *, task_gib, reads_disk=False):
    """在有限窗口内提交任务，按输入顺序消费结果。"""
    budget = runtime["effective"]
    if budget["memory_gib"] < task_gib:
        raise MemoryError(f"当前内存预算不足以运行单个任务，至少需要 {task_gib:g} GiB。")
    limit = budget["io_workers" if reads_disk else "workers"]
    limit = max(1, min(limit, int(budget["memory_gib"] / task_gib)))
    if limit == 1:
        for task in tasks:
            available = memory_gib()[1]
            if available is not None and available < 1 + task_gib:
                raise MemoryError(f"当前可用内存不足，无法派发需要 {task_gib:g} GiB 的任务。")
            yield function(task)
        return
    iterator = iter(tasks)
    pending = deque()
    with ProcessPoolExecutor(max_workers=limit, mp_context=multiprocessing.get_context("spawn")) as pool:
        exhausted = False
        try:
            while pending or not exhausted:
                available = memory_gib()[1]
                slots = limit if available is None else min(limit, int(max(0, available - 1) / task_gib))
                if not slots and not pending:
                    raise MemoryError(f"当前可用内存不足，无法派发需要 {task_gib:g} GiB 的任务。")
                while len(pending) < slots and not exhausted:
                    try:
                        task = next(iterator)
                    except StopIteration:
                        exhausted = True
                        break
                    with _spawn_lock:
                        prior = {key: os.environ.get(key) for key in _thread_variables}
                        try:
                            os.environ.update(dict.fromkeys(_thread_variables, "1"))
                            pending.append(pool.submit(function, task))
                        finally:
                            for key, value in prior.items():
                                if value is None:
                                    os.environ.pop(key, None)
                                else:
                                    os.environ[key] = value
                if pending:
                    yield pending.popleft().result()
        finally:
            for future in pending:
                future.cancel()
