"""M7固定空间块尺度敏感性，采用与M2相同的球面等面积投影。
作者：Codex。输入完整格点清单、冻结边界bbox和params；输出格点到块映射。
仅经统一入口调用，不修改M2格点清单或M5连接诊断。
"""
import numpy as np


def fixed_blocks(grid, bbox, size, params):
    """以冻结边界中心为投影原点；块边界与M2算法一致。"""
    if size <= 0 or bbox is None or len(bbox) != 4:
        raise ValueError("空间尺度敏感性缺少有效冻结边界或块宽。")
    west, south, east, north = bbox
    lat0 = np.deg2rad((south+north)/2)
    lon0 = (west+east)/2
    radius = params["native_era5land"]["earth_radius_km"]
    result = {}
    for cell in grid:
        lat = np.deg2rad(cell["lat"])
        dlon = np.deg2rad(cell["lon"]-lon0)
        factor = np.sqrt(2/(1+np.sin(lat0)*np.sin(lat)+np.cos(lat0)*np.cos(lat)*np.cos(dlon)))
        x = radius*factor*np.cos(lat)*np.sin(dlon)
        y = radius*factor*(np.cos(lat0)*np.sin(lat)-np.sin(lat0)*np.cos(lat)*np.cos(dlon))
        result[cell["grid_id"]] = f"{int(np.floor(x/size))}:{int(np.floor(y/size))}"
    return result
