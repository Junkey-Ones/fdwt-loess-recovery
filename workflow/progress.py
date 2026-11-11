"""运行事件、滑动速度和本地历史估时。"""
from collections import deque
from dataclasses import dataclass
from hashlib import sha256
import json
from statistics import median
from threading import Lock
from time import monotonic
from uuid import uuid4


@dataclass(frozen=True)
class ProgressEvent:
    module: str
    stage: str
    detail: str = ""
    done: int = 0
    total: int | None = None
    unit: str = ""
    state: str = "running"


def emit(callback, module, stage, detail="", *, done=0, total=None, unit="", state="running"):
    """优先传递结构化事件，兼容原有三参数回调。"""
    if callback is None:
        return
    event = ProgressEvent(module, stage, detail, done, total, unit, state)
    if hasattr(callback, "event"):
        callback.event(event)
    else:
        callback(f"{module} {stage}", detail, done / total if total else float(state == "passed"))


def duration(seconds):
    """以秒、分秒或小时分钟显示时长。"""
    if seconds is None:
        return "暂无法估算"
    hours, rest = divmod(max(0, round(seconds)), 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours} 小时 {minutes:02d} 分"
    return f"{minutes} 分 {seconds:02d} 秒" if minutes else f"{seconds} 秒"


TERMINAL = {"passed", "reused", "conditional_skipped", "descriptive_only", "exited", "failed", "interrupted"}
LABELS = {"running": "运行中", "waiting": "等待", "passed": "通过", "reused": "已复用",
          "conditional_skipped": "条件跳过", "descriptive_only": "描述性完成", "exited": "按门槛退出",
          "failed": "失败", "interrupted": "已中断"}


class RunProgress:
    """将事件汇成线程安全快照。估时使用最近 30 秒的工作量差。"""

    def __init__(self, clock=monotonic):
        self.clock = clock
        self.lock = Lock()
        self.started = self.stage_started = self.updated = clock()
        self.current = ProgressEvent("", "核对运行计划")
        self.modules = {}
        self.history = {}
        self.module_started = {}
        self.durations = {}
        self.samples = deque()
        self.phase_durations = {}
        self.terminal = None
        self.history_target = None
        self.on_stage_change = None
        self.forecasts = []
        self.last_forecast = None

    def configure_run(self, root, plan, params):
        """读取可比的本机成功记录。来源发生变化时弃用旧估时。"""
        logs = root / params["output"]["logs"]
        run_logs = logs / plan["run_alias"]
        self.configure(plan["modules"], {})
        if plan["modules"] == ["M0"]:
            return
        try:
            identity = json.loads((run_logs / "run.json").read_bytes())
            from src.M1.scr_audit_era5land import era5land_years, expected_files

            native = params["native_era5land"]
            paths = {path.as_posix() for path, *_ in expected_files(native, *era5land_years(params))}
            paths.add(native["evidence"])
            supplement = params["downstream"]["supplement_manifest"]
            if any(int(module[1:]) >= 3 for module in plan["modules"]):
                paths.add(supplement)
                if (root / supplement).is_file():
                    for entry in json.loads((root / supplement).read_bytes()).values():
                        if entry.get("status") == "accepted":
                            paths.add(entry["path"])
                            paths.update(item["path"] for item in entry["sources"])
            files = []
            for name in sorted(paths):
                path = (root / name).resolve()
                if not path.is_relative_to(root):
                    return
                info = path.stat()
                files.append((name, info.st_size, info.st_mtime_ns))
            modes = [(module, (run_logs / f"module_io_{module}.json").is_file())
                     for module in plan["modules"]]
            runtime = plan["runtime"]
            effective = runtime["effective"]
            capacity = (runtime["profile"], effective["workers"], effective["io_workers"],
                        int(effective["memory_gib"]))
            signature = sha256(json.dumps([identity["run_id"], plan["product_combo"], plan["variant"],
                                           capacity, modes, files],
                                          sort_keys=True).encode()).hexdigest()
            records = []
            candidates = sorted(logs.glob("*/progress_*.json"), key=lambda path: path.stat().st_mtime_ns)
            for path in candidates[-40:]:
                try:
                    records.append(json.loads(path.read_bytes()))
                except (OSError, ValueError):
                    continue
            self.configure(plan["modules"], history_medians(records, signature))
            self.history_target = run_logs / f"progress_{uuid4().hex}.json", signature
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return

    def save_history(self):
        """追加成功运行的非冻结计时日志。"""
        if self.history_target is None or self.terminal != "passed":
            return
        from .freeze_m0 import atomic_write, json_bytes

        path, signature = self.history_target
        timings = [[module, "", seconds] for module, seconds in self.durations.items()
                   if self.modules[module] in {"passed", "reused", "descriptive_only"}]
        timings.extend([module, phase, seconds] for (module, phase), seconds in self.phase_durations.items()
                       if self.modules[module] in {"passed", "reused", "descriptive_only"})
        if timings:
            atomic_write(path, json_bytes(dict(signature=signature, timings=timings,
                                               eta_validation=self.forecast_accuracy())))

    def observe(self, snapshot):
        """抽样记录界面有依据和无依据的估时，用于运行结束后复核。"""
        event = snapshot["event"]
        if not event.module or event.state != "running" or snapshot["terminal"]:
            return
        key = (event.module, event.stage, int(snapshot["elapsed"] // 15),
               event.total is not None, snapshot["eta"] is not None, snapshot["total_eta"] is not None)
        with self.lock:
            if key != self.last_forecast:
                self.last_forecast = key
                self.forecasts.append((key[:2], snapshot["stage_elapsed"], snapshot["elapsed"],
                                       snapshot["eta"], snapshot["total_eta"], event.total is not None))

    def forecast_accuracy(self):
        """分别汇总本次观测阶段 ETA 与历史加权总 ETA 的覆盖和误差。"""
        with self.lock:
            rows = tuple(self.forecasts)
            phases = dict(self.phase_durations)
            elapsed = (self.finished_at if self.terminal else self.clock()) - self.started
        local = [None if estimate is None else abs(estimate - max(0, phases[key] - stage_elapsed))
                 for key, stage_elapsed, _, estimate, _, countable in rows if key in phases and countable]
        total = [None if estimate is None else abs(estimate - max(0, elapsed - run_elapsed))
                 for _, _, run_elapsed, _, estimate, _ in rows]

        def summary(errors):
            valid = [error for error in errors if error is not None]
            return dict(samples=len(errors), estimates=len(valid), median_absolute_error_seconds=median(valid) if valid else None)

        return {"observed_stage": summary(local), "historical_total": summary(total)}

    def configure(self, modules, history):
        with self.lock:
            self.modules = dict.fromkeys(modules, "waiting")
            self.history = history

    def event(self, event):
        with self.lock:
            now = self.clock()
            old = self.current
            changed = (old.module, old.stage) != (event.module, event.stage)
            if changed:
                if old.module and old.state == "running":
                    self.phase_durations[old.module, old.stage] = now - self.stage_started
                self.stage_started = self.updated = now
                self.samples.clear()
            if event.done > (0 if changed else old.done):
                self.samples.append((now, event.done))
                self.updated = now
            while self.samples and self.samples[0][0] < now - 30:
                self.samples.popleft()
            self.current = event
            if event.module:
                self.modules[event.module] = event.state
                self.module_started.setdefault(event.module, now)
                if event.state in TERMINAL:
                    self.durations[event.module] = now - self.module_started[event.module]
        if (changed or old.state != event.state) and self.on_stage_change is not None:
            self.on_stage_change()

    def __call__(self, step, detail, fraction):
        self.event(ProgressEvent(self.current.module, step, detail, round((fraction or 0) * 100), 100))

    def finish(self, state):
        with self.lock:
            self.terminal = state
            self.finished_at = self.clock()
            if state in {"failed", "interrupted"} and self.current.module:
                if self.modules.get(self.current.module) == "running":
                    self.modules[self.current.module] = state

    def snapshot(self):
        with self.lock:
            now = self.finished_at if self.terminal else self.clock()
            event = self.current
            stale = now - self.updated
            samples = [(t, n) for t, n in self.samples if t >= now - 30]
            speed = eta = None
            if len(samples) >= 3 and event.unit and event.state == "running":
                span = samples[-1][0] - samples[0][0]
                if span > 0 and stale < 30:
                    speed = (samples[-1][1] - samples[0][1]) / span
                    if event.total is not None:
                        eta = max(0, event.total - event.done) / speed
            fraction = min(0.999, event.done / event.total) if event.total and event.state == "running" else None
            remaining = []
            for module, state in self.modules.items():
                if state in TERMINAL:
                    continue
                estimate = self.history.get(module)
                if estimate is None:
                    remaining.append(None)
                elif state == "running":
                    elapsed = now - self.module_started[module]
                    historical_stage = self.history.get((module, event.stage))
                    if stale >= 30 or (eta is None and elapsed >= estimate):
                        remaining.append(None)
                    elif eta is not None and historical_stage is not None:
                        prior = sum(self.history.get(key, seconds) for key, seconds in self.phase_durations.items()
                                    if key[0] == module)
                        tail = max(0, estimate - prior - historical_stage)
                        remaining.append(eta + tail)
                    else:
                        remaining.append(max(0, estimate - elapsed))
                else:
                    remaining.append(estimate)
            total_eta = None if not remaining or None in remaining else sum(remaining)
            elapsed = now - self.started
            overall = min(0.999, elapsed / (elapsed + total_eta)) if total_eta is not None and elapsed + total_eta else None
            if self.terminal == "passed":
                overall, total_eta = 1.0, 0
            elif self.terminal:
                overall = total_eta = eta = speed = None
            return dict(event=event, elapsed=elapsed, stage_elapsed=now - self.stage_started, stale=stale,
                        speed=speed, eta=eta, fraction=fraction, overall=overall, total_eta=total_eta,
                        modules=dict(self.modules), terminal=self.terminal)


def history_medians(records, signature):
    """仅用同签名的成功阶段记录，忽略损坏和旧格式。"""
    samples = {}
    for record in records:
        if not isinstance(record, dict) or record.get("signature") != signature:
            continue
        timings = record.get("timings")
        if not isinstance(timings, list):
            continue
        for entry in timings:
            try:
                module, phase, seconds = entry
                if not isinstance(module, str) or not isinstance(phase, str) or not 0 < seconds < float("inf"):
                    continue
                samples.setdefault((module, phase) if phase else module, []).append(seconds)
            except (TypeError, ValueError):
                continue
    return {key: median(values) for key, values in samples.items() if len(values) >= 2}
