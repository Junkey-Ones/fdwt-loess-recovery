"""脚本名：scr_spatial_inference.py（M7 · 空间抽样规则）

功能简介：选择固定空间块或历史超级块，保留连接诊断与抽样单元的区别。
作者：Codex
版本：v0.1.0（2026-11-15）
读取数据：统一入口传入的参数、M2空间块和M5超级块映射。
生成数据：内存中的抽样标签；由M7写入登记表。
其他文件：日志和输出路径由统一入口管理。
运行示例：python -m workflow.run_module M7
退出码：由统一入口定义。
"""


def resampling_scheme(params):
    """读取抽样单元；旧冻结参数未声明时保持原超级块行为。"""
    scheme = params["block"].get("resampling_unit", "superblock")
    if scheme not in {"fixed_space", "superblock"}:
        raise ValueError("空间抽样单元仅支持 fixed_space 或 superblock。")
    if params["block"]["two_way_cluster"] != ["space", "year"]:
        raise ValueError("路线一依赖修正须同时保留空间块和事件起始年份。")
    return scheme


def resampling_label(block, superblocks, params):
    """固定空间规则不传播区域事件连接；旧规则严格检查超级块映射。"""
    if block is None:
        return None
    if resampling_scheme(params) == "fixed_space":
        return block
    if block not in superblocks:
        raise ValueError(f"空间块缺少超级块登记：{block}")
    return superblocks[block]


def bootstrap_method(params):
    """为结果表提供实际使用的抽样方法名称。"""
    return "fixed_space_bootstrap" if resampling_scheme(params) == "fixed_space" else "superblock_bootstrap"
