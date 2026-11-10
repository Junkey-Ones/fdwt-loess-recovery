"""从冻结结果生成论文矢量图与可追溯图件清单。
作者：Codex。版本：v0.1.0。输入：M5、M9 和 M10 的冻结表。
输出：PDF、SVG、PNG 和图注清单，由统一入口发布。
运行：python -m workflow.run_module M10。退出码由统一入口定义。
"""
from collections import Counter
from math import isfinite

import numpy as np

BLUE = "#17648a"
ORANGE = "#b5522b"
INK = "#222c33"
MUTED = "#56626a"
GRID = "#d9e0e4"
MM_PER_INCH = 25.4
STYLE = {
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans"],
    "font.size": 7,
    "axes.labelsize": 7,
    "axes.titlesize": 7,
    "xtick.labelsize": 6,
    "ytick.labelsize": 6,
    "legend.fontsize": 6,
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": MUTED,
    "xtick.color": INK,
    "ytick.color": INK,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.linewidth": 0.55,
    "xtick.major.width": 0.55,
    "ytick.major.width": 0.55,
    "pdf.fonttype": 42,
    "svg.fonttype": "none",
    "svg.hashsalt": "fdwt-v1.3.1",
}


def panel(ax, letter, title):
    """设置字母分面和简短标题。"""
    ax.set_title(f"$\\bf{{{letter}}}$   {title}", loc="left", pad=7)
    ax.set_axisbelow(True)


def sample_flow(figure, rows):
    """显示各步保留及排除计数，共用零基线。"""
    ax = figure.subplots()
    labels = ["Eligible episodes", "Observed recovery", "Active-season endpoints", "Classifiable rainfall"]
    rows = sorted(rows, key=lambda row: row["step_order"])
    kept = [row["n_after"] for row in rows]
    excluded = [row["n_excluded"] for row in rows]
    y = np.arange(len(rows))
    ax.barh(y, kept, color=BLUE, height=0.56, label="Retained")
    ax.barh(y, excluded, left=kept, color=GRID, height=0.56, label="Excluded")
    max_count = max(1, max(row["n_before"] for row in rows))
    for i, row in enumerate(rows):
        ax.text(row["n_before"] + max_count * 0.025, i,
                f'{row["n_after"]:,} / {row["n_before"]:,}', va="center", fontsize=6)
    ax.set(xlim=(0, max_count * 1.32), yticks=y, yticklabels=labels,
           xlabel="Number of grid-cell episodes")
    ax.invert_yaxis()
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.legend(loc="lower center", bbox_to_anchor=(.5, 1), ncols=2, frameon=False)
    return "Sequential eligibility counts. Labels report retained / entering each step."


def recovery_dynamics(figure, events):
    """绘制条件 A 恢复时间、幅度与速率的经验分布。"""
    axes = figure.subplots(1, 3)
    labels = (("RT", "Recovery time", "Time (pentads)"),
              ("delta_SMP", "Recovery magnitude", "Change (percentile points)"),
              ("RR", "Recovery rate", "Rate (percentile points per pentad)"))
    for ax, letter, (key, title, xlabel) in zip(axes, "abc", labels):
        values = np.sort([event[key] for event in events])
        proportion = np.arange(1, len(values)+1) / len(values)
        ax.step(np.r_[values[0], values], np.r_[0, proportion], where="post", color=BLUE, lw=1.25)
        ax.axvline(np.median(values), color=ORANGE, ls="--", lw=0.85)
        ax.set(xlabel=xlabel, ylim=(0, 1.05), yticks=[0, .25, .5, .75, 1])
        ax.text(.97, .05, f"n = {len(values):,}", transform=ax.transAxes, ha="right", color=MUTED)
        ax.grid(axis="y", color=GRID, lw=0.45)
        panel(ax, letter, title)
    axes[0].set_ylabel("Empirical cumulative proportion")
    return "Empirical distributions among recovered episodes with active-season endpoints. Dashed lines denote medians."


def rainfall_transition(figure, events):
    """分列未知窗口，并保留 F_R 阳性的离散滞后结构。"""
    a, b = figure.subplots(1, 2, gridspec_kw={"width_ratios": [1, 1.2]})
    counts = Counter(event["F_R_subtype"] if event["F_R"] is True else
                     "negative" if event["F_R"] is False else "unknown" for event in events)
    groups = ["pre", "sync", "post", "negative", "unknown"]
    positions = np.arange(len(groups))
    heights = [counts[group] for group in groups]
    a.barh(positions, heights, color=[BLUE, BLUE, BLUE, MUTED, GRID], height=.56)
    a.set(yticks=positions, yticklabels=["Before recovery", "At recovery", "After recovery", "No F$_R$", "Unknown"],
          xlabel="Number of grid-cell episodes", xlim=(0, max(heights)*1.24))
    a.invert_yaxis()
    for y, count in enumerate(heights):
        a.annotate(f"{count:,}", (count, y), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6)
    positive = [event["Lag_FR"] for event in events if event["F_R"] is True]
    if positive:
        lag = Counter(positive)
        b.bar(sorted(lag), [lag[x] for x in sorted(lag)], color=ORANGE, width=.75)
    else:
        b.text(.5, .5, "No F$_R$-positive episodes", ha="center", va="center", transform=b.transAxes)
    b.set(xlabel="Lag from minimum SMP (pentads)", ylabel="Number of F$_R$ episodes")
    panel(a, "a", "Rainfall classification")
    panel(b, "b", "Lag among F$_R$ episodes")
    return "Counts among eligible recovered episodes. Unknown windows are shown separately. Lag is defined for F_R-positive episodes only."


def cross_product(figure, rows):
    """区分双向匹配率和 Jaccard 指数，绘制同支撑事件一致性。"""
    ax = figure.subplots()
    rows = sorted(rows, key=lambda row: row["product_combo"])
    metrics = (("main_hit", "Reference match rate", "o", BLUE),
               ("alt_hit", "Alternative match rate", "s", ORANGE),
               ("jaccard", "Jaccard index", "^", MUTED))
    for offset, (key, label, marker, color) in zip((-.2, 0, .2), metrics):
        points = [(row[key], i+offset) for i, row in enumerate(rows) if row[key] is not None]
        if points:
            x, y = zip(*points)
            ax.scatter(x, y, label=label, marker=marker, color=color, s=16)
    ax.set(xlim=(0, 1.02), yticks=range(len(rows)),
           yticklabels=[row["product_combo"].replace("__", " / ") for row in rows],
           xlabel="Event agreement")
    ax.grid(axis="x", color=GRID, lw=.45)
    ax.legend(loc="lower center", bbox_to_anchor=(.5, 1), ncols=3, frameon=False)
    return "One-to-one event matching on common support. Agreement concerns event lists."


def export_figures(directory, inputs, context):
    """按可用冻结表导出图件，返回源表、图注和缺项原因。"""
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator

    events = [row for row in inputs["event_master"] if row["route1_A_eligible"]]
    recovery = [row for row in events if all(row[k] is not None and isfinite(row[k])
                                            for k in ("RT", "delta_SMP", "RR"))]
    flow = inputs["sample_flow"]
    agreement = [row for row in inputs["cross_product_match_summary"] if row["jaccard"] is not None]
    specs = [
        ("fig01_sample_flow", "sample_flow", flow if any(row["n_before"] for row in flow) else [],
         sample_flow, (89, 61), "样本流无事件"),
        ("fig02_recovery_dynamics", "event_master", recovery, recovery_dynamics, (183, 58), "无可绘制的条件 A 恢复数据"),
        ("fig03_fr_and_lag", "event_master", events, rainfall_transition, (183, 66), "无可绘制的条件 A 接续数据"),
        ("fig04_lai_deep_effects", "model_marginal", [], None, None, "尚无可发布的 Q3 冻结模型结果"),
        ("fig05_cross_product_robustness", "cross_product_match_summary", agreement, cross_product,
         (183, 63), "缺少同支撑的跨产品匹配结果"),
        ("fig06_specification_curve", "spec_result", [], None, None, "尚无可发布的规范复算结果"),
        ("fig07_route2_paths", "route2_path_estimate", [], None, None, "尚无通过门槛的路线二路径估计"),
    ]
    manifest = []
    with rc_context(STYLE):
        for name, source, rows, render, size, missing in specs:
            entry = {"figure": name, "source_table": source, "n_source_rows": len(rows), **context}
            if not rows:
                manifest.append({**entry, "status": "omitted", "reason": missing})
                continue
            directory.mkdir(parents=True, exist_ok=True)
            figure = Figure(figsize=tuple(mm/MM_PER_INCH for mm in size), layout="constrained")
            FigureCanvasAgg(figure)
            caption = render(figure, rows)
            for ax in figure.axes:
                if render is rainfall_transition and ax is figure.axes[1]:
                    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
                if (render is rainfall_transition and ax is figure.axes[0]) or render is sample_flow:
                    ax.xaxis.set_major_locator(MaxNLocator(nbins=4, integer=True))
            files = []
            for extension, metadata in (("pdf", {"CreationDate": None}), ("svg", {"Date": None}), ("png", {})):
                filename = f"{name}.{extension}"
                figure.savefig(directory / filename, dpi=600, metadata=metadata)
                files.append(filename)
            manifest.append({**entry, "status": "exported", "width_mm": size[0], "height_mm": size[1],
                             "caption": caption, "files": files})
            figure.clear()
    return manifest
