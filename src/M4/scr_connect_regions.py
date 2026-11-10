"""连接时空邻接格点事件，按实际格点面积汇总区域事件。
作者：Codex。版本：v0.1.0。运行：python -m workflow.run_module M4。
日志、路径和退出码由统一入口管理。
"""
from collections import defaultdict


def connect_regions(events, grid, params):
    """同候及相邻候按四邻域连接，输出区域和成员长表。"""
    resolution = params["grid"]["resolution_deg"]
    positions = {row["grid_id"]: (round(row["lon"]/resolution), round(row["lat"]/resolution)) for row in grid}
    areas = {row["grid_id"]: row["area_km2"] for row in grid}
    parents = {}

    def find(key):
        while parents[key] != key:
            parents[key] = parents[parents[key]]
            key = parents[key]
        return key

    nodes = defaultdict(list)
    for event in events:
        key = event["episode_id"]
        parents[key] = key
        x, y = positions[event["grid_id"]]
        stop = event["t_e"] if event["t_e"] is not None else event["censor_t_abs"]
        for t in range(event["t_s"], stop+1):
            nodes[event["product"], event["support_id"], t, x, y].append(event)
    for (product, support, t, x, y), current in nodes.items():
        for offset in (0, 1):
            for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                neighbors = nodes.get((product, support, t+offset, x+dx, y+dy), ())
                for a in current:
                    for b in neighbors:
                        left, right = find(a["episode_id"]), find(b["episode_id"])
                        if left != right:
                            parents[max(left, right)] = min(left, right)
    groups = defaultdict(list)
    for event in events:
        groups[find(event["episode_id"])].append(event)
    regional, members = [], []
    for root, group in sorted(groups.items()):
        start = min(row["t_s"] for row in group)
        initial = {row["grid_id"] for row in group if row["t_s"] == start}
        if len(initial) < params["drought"]["regional_initial_min_cells"]:
            continue
        end = start
        cluster = f"region:{root}"
        footprint = {row["grid_id"] for row in group}
        for row in group:
            row["cluster_id"] = cluster
            cell = row["grid_id"]
            stop = row["t_e"] if row["t_e"] is not None else row["censor_t_abs"]
            end = max(end, stop)
            members.extend(dict(cluster_id=cluster, episode_id=row["episode_id"], t_abs=t,
                                grid_id=cell, cell_area_km2=areas[cell], connected_flag=True, footprint_flag=True)
                           for t in range(row["t_s"], stop+1))
        regional.append(dict(cluster_id=cluster, product=group[0]["product"], definition_id="main",
                             start_t_abs=start, end_t_abs=end, n_grid_episodes=len(group),
                             footprint_area_km2=sum(areas[cell] for cell in footprint),
                             initial_footprint_cells=len(initial), regional_qc_status="passed"))
    return regional, members
