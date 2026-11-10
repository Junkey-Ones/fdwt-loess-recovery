"""脚本名：scr_audit_protocol.py（M0 · 协议冻结前审计）

功能简介：核对协议、参数、表结构和验收登记，给出冻结阻断项。
作者：Codex
版本：v0.1.0
读取数据：运行入口提供的配置、协议原文及登记。
生成数据：返回检查明细和输入 SHA-256，由入口封存审计日志。
其他文件：不读取科学结局。
运行示例：python -m workflow.run_module，选择 M0。
退出码：由统一入口根据审计状态确定。
"""

import csv
import hashlib
from io import StringIO
import json
from math import isclose, radians, sin
import re


def verify_rectangle(row, inputs):
    """复核登记矩形的文件哈希、经纬度环及球面面积。"""
    content = inputs.get(row["file_name"])
    if content is None or hashlib.sha256(content).hexdigest() != row["file_sha256"]:
        return False
    try:
        feature = json.loads(content)
        west, south, east, north = json.loads(row["bbox"])
        ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
        # 球面面积换算采用登记所列的平均地球半径。
        area = 6371.0088 ** 2 * radians(east - west) * (sin(radians(north)) - sin(radians(south)))
        return (
            -180 <= west < east <= 180 and -90 <= south < north <= 90
            and feature["type"] == "Feature" and feature["id"] == row["boundary_id"]
            and feature["geometry"] == {"type": "Polygon", "coordinates": [ring]}
            and row["source_crs"] == "OGC:CRS84" and row["geometry_type"] == "Polygon"
            and row["feature_count"] == "1" and row["validity_status"] == "valid"
            and isclose(area, float(row["area_km2_equal_area"]), abs_tol=0.001)
        )
    except (KeyError, ValueError, TypeError):
        return False


def verify_specifications(matrix, params):
    """校验逐项枚举、族内设置、计数以及科学参数引用。"""
    reference = matrix["reference"]
    families = matrix["families"]
    settings = matrix["variant_settings"]
    variants = [item for family in families.values() for item in family if item != reference]
    if (matrix["combination_policy"] != "one_family_at_a_time" or not families
            or any(family.count(reference) != 1 for family in families.values())
            or len(variants) != len(set(variants)) or set(variants) != set(settings)):
        return False
    for entry in matrix["estimands"].values():
        expected = [reference, *(item for name in entry["families"]
                                 for item in families[name] if item != reference)]
        excluded = entry.get("excluded_variants", [])
        if reference in excluded or not set(excluded).issubset(expected):
            return False
        expected = [item for item in expected if item not in excluded]
        if (entry["specifications"] != expected or entry["n_specifications"] != len(expected)
                or len(expected) != len(set(expected))):
            return False
    for variant in settings.values():
        for key, value in variant.items():
            if key.endswith("_ref"):
                node = params
                for part in value.split("."):
                    node = node[part]
            if key == "product_combo" and value not in params["products"]["combinations"]:
                return False
    return bool(matrix["estimands"] and matrix["applicability"])


def audit_protocol(params, schema, matrix, freeze, documents, inputs):
    """检查已登记输入并返回逐项判定。inputs 为相对路径到原始字节的映射。"""
    checks = []

    def record(check_id, condition, detail, otherwise="failed"):
        checks.append({"check_id": check_id, "status": "passed" if condition else otherwise,
                       "detail": detail})

    version = params["protocol"]["version"]
    record("protocol_version",
           version == schema["schema_version"] == matrix["protocol_version"] == freeze["protocol_version"]
           and all(version in inputs[path].decode("utf-8-sig").partition("\n")[0]
                   for path in documents),
           "协议原文、参数、Schema、规范矩阵和冻结登记的版本一致性")

    overall = [params["time"]["year_start"], params["time"]["year_end"]]
    complete = params["lai"]["complete_years"]
    exposure = params["lai"]["exposure_years"]
    common = params["ndvi"]["common_sample_years"]
    window = params["lai"]["window_years"]
    record("year_windows", overall[0] <= complete[0] < exposure[0] <= exposure[1] == overall[1]
           and complete[1] == overall[1] and exposure[0] == complete[0] + window
           and params["lai"]["main_requires_full"] == window and common == exposure,
           "四层时期、事件前完整年窗与共同样本的内部一致性")
    first, last = params["clim"]["base_window"]
    cov_first, cov_last = params["covariates"]["climate_years"]
    record("calendar_coverage",
           params["time"]["index_base_year"] == 2000
           and params["time"]["pentads_per_year"] == 73
           and 2000 <= first <= last <= overall[1]
           and 2000 <= cov_first <= cov_last <= overall[1],
           "候索引遵守 SOP，气候态和背景气候期必须可由 M1/M2 覆盖")
    record("time_origins",
           (params["route1"]["recovery_risk_t0"], params["route2"]["t0"]) == ("t_min", "t_s"),
           "路线一恢复风险从 t_min 起算，路线二从 t_s 起算")
    record("precip_windows",
           params["fr"]["window"] == params["fz"]["window"]
           and params["fr"]["percentile"] == params["pterm"]["percentile"]
           and params["fr"]["min_p_mm"] == params["pterm"]["min_p_mm"],
           "接续判定窗以及 F_R 与 P-term 使用的降水阈值内部一致性")
    tests = params["multiple_testing"]
    families = tests["families"]
    members = [member for family in families.values() for member in family]
    record("test_families", set(families) == {"q1", "q2", "q3"}
           and all(families.values()) and len(members) == len(set(members))
           and tests["family_adjustment"] == "holm",
           "Q1、Q2、Q3 独立登记，检验成员互斥，按家族执行 Holm")
    for name, table in schema["tables"].items():
        columns = table["columns"]
        key = table.get("primary_key", [])
        missing = sorted(set(key) - set(columns))
        record(f"schema_{name}", bool(columns) and len(columns) == len(set(columns))
               and len(key) == len(set(key)) and not missing,
               f"{name} 主键缺列 {', '.join(missing)}" if missing else f"{name} 列和主键声明")

    for directory, name in (("config", "deviation_log"), ("metadata", "source_file_manifest"),
                            ("metadata", "source_variable_map"), ("metadata", "study_area_manifest")):
        path = f"{directory}/{name}.csv"
        rows = list(csv.reader(StringIO(inputs[path].decode("utf-8-sig"), newline="")))
        record(f"header_{name}", bool(rows) and rows[0] == schema["tables"][name]["columns"],
               f"{path} 表头与 Schema 一致性")
        if name in {"source_file_manifest", "source_variable_map"}:
            record(f"registration_{name}", False,
                   f"{name} 当前有 {max(0, len(rows) - 1)} 条登记，产品与实文件放行由 M1 验收",
                   "not_run")

    seed = params["random"]
    record("random_seed",
           freeze["random_seed_status"] == "frozen" and type(seed["seed"]) is int
           and seed["seed"] >= 0 and isinstance(seed["seed_id"], str)
           and seed["seed_id"] == freeze.get("random_seed_id")
           and bool(re.fullmatch(r"[A-Za-z0-9_-]+", seed["seed_id"])),
           "随机种子与 seed_id 须在看结局前由负责人登记", "conditional_skipped")
    boundary_id = freeze.get("research_boundary_id")
    boundaries = csv.DictReader(StringIO(inputs["metadata/study_area_manifest.csv"].decode("utf-8-sig")))
    deviations = csv.DictReader(StringIO(inputs["config/deviation_log.csv"].decode("utf-8-sig")))
    approved = any(row["deviation_id"] == freeze.get("research_boundary_deviation_id")
                   and row["status"] == "approved" for row in deviations)
    selected = [row for row in boundaries if row["boundary_id"] == boundary_id]
    record("research_boundary", freeze["research_boundary_status"] == "frozen"
           and approved and len(selected) == 1 and selected[0]["acceptance_status"] == "accepted"
           and verify_rectangle(selected[0], inputs),
           "研究区矩形的登记、偏离审批、SHA-256、几何及球面面积复核",
           "failed" if freeze["research_boundary_status"] == "frozen" else "conditional_skipped")
    for asset, label in (("station", "独立站点"), ("circulation", "可选环流")):
        record(asset, False, f"{label}放行待对应模块核对正式登记与实文件证据", "not_run")
    record("specification_enumeration", matrix["freeze_status"] == "frozen"
           and verify_specifications(matrix, params),
           "按估计对象逐项枚举规范并登记适用规则")
    return {
        "protocol_version": version,
        "registration": "internal_preregistration_freeze" if not freeze["external_registration_id"]
        else "external_registration_recorded",
        "status": "failed" if any(row["status"] == "failed" for row in checks) else "descriptive_only",
        "formal_freeze_written": False,
        "regional_release": False,
        "checks": checks,
        "input_sha256": {path: hashlib.sha256(content).hexdigest() for path, content in inputs.items()},
    }
