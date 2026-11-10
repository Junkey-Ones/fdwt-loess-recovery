"""匹配不同产品格点事件。输入同支撑事件表，输出最优一对一匹配。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M9。
日志、路径和退出码由统一入口管理。
"""
from collections import defaultdict


def match_grid_events(reference, alternative, tolerance):
    """同格点按最大匹配数、最小总时差匹配有序事件。"""
    groups = defaultdict(lambda: ([], []))
    for side, events in enumerate((reference, alternative)):
        for event in events:
            groups[event["grid_id"]][side].append(event)
    matches = []
    for grid_id, (left, right) in sorted(groups.items()):
        if not left or not right:
            continue
        left.sort(key=lambda row: (row["t_s"], row["episode_id"]))
        right.sort(key=lambda row: (row["t_s"], row["episode_id"]))
        previous = [(0, 0, ()) for _ in range(len(right)+1)]
        for a in left:
            current = [previous[0]]
            for j, b in enumerate(right, 1):
                options = [current[-1], previous[j]]
                ds, dm = b["t_s"]-a["t_s"], b["t_min"]-a["t_min"]
                if max(abs(ds), abs(dm)) <= tolerance:
                    n, cost, pairs = previous[j-1]
                    options.append((n+1, cost-abs(ds)-abs(dm), (*pairs, (a["episode_id"], b["episode_id"], ds, dm))))
                current.append(max(options, key=lambda item: item[:2]))
            previous = current
        matches.extend(dict(grid_id=grid_id, main_episode_id=a, alt_episode_id=b, delta_ts=ds, delta_tmin=dm)
                       for a, b, ds, dm in previous[-1][2])
    return matches
