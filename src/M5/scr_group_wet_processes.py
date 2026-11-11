"""为连续合格降水候建立湿过程及空间超级块。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M5。
输入：M2 格点、M3 候和 M5 结局。输出：湿过程与超级块成员。
"""
from collections import defaultdict

from src.M5.scr_derive_outcomes import index_series, precip_qualifies


def assign_wet_processes(events, branches, rows, params):
    """按完整格点时间轴登记湿过程，并将过程键连接到事件。"""
    index = index_series(rows)
    minimum = params["fr"]["min_p_mm"]
    membership, at_time = [], {}
    for key, series in sorted(index.items()):
        previous = None
        process = None
        for t, row in sorted(series.items()):
            if not precip_qualifies(row, minimum):
                continue
            if previous is None or t != previous+1:
                process = ":".join(map(str, (*key, t)))
            previous = t
            at_time[(*key, t)] = process
            membership.append(dict(wet_process_id=process, product_combo=key[0], grid_id=key[1],
                                   support_id=key[2], t_abs=t))
    event_by_id = {row["episode_id"]: row for row in events}
    for branch in branches:
        event = event_by_id[branch["episode_id"]]
        key = (event["product"], event["grid_id"], event["support_id"], branch["t_w"])
        process = at_time.get(key)
        branch["wet_process_id"] = process
        if branch["branch"] == "F_R":
            event["wet_process_id"] = process
    return membership


def build_superblocks(events, grids):
    """汇合所有格点后连接共享区域事件或湿过程的空间块。"""
    blocks = {row["grid_id"]: row["block_id"] for row in grids}
    parent = {block: block for block in blocks.values() if block is not None}

    def find(block):
        while parent[block] != block:
            parent[block] = parent[parent[block]]
            block = parent[block]
        return block

    shared = defaultdict(set)
    for event in events:
        block = blocks[event["grid_id"]]
        if block is None:
            continue
        for name in ("cluster_id", "wet_process_id"):
            if event.get(name):
                shared[name, event[name]].add(block)
    for group in shared.values():
        first, *rest = sorted(group)
        for block in rest:
            a, b = find(first), find(block)
            parent[max(a,b)] = min(a,b)
    return [dict(block_id=block, superblock_id=find(block)) for block in sorted(parent)]


def group_wet_processes(events, branches, rows, grids, params):
    """给连续湿候分配过程标识，连接共享区域事件的空间块。"""
    membership = assign_wet_processes(events, branches, rows, params)
    return membership, build_superblocks(events, grids)
