"""M7继承边界：下游增项允许，上游科学修改和链篡改拒绝。"""
import hashlib
import json
import yaml
import pytest
from workflow.run_module import DEFAULT_CONFIG, load_config
from workflow.inherit_upstream import upstream_projection, validate_receipt_chain
from src.M7.scr_block_sensitivity import fixed_blocks


def test_projection_preserves_upstream_science():
    """只剔除白名单M7配置；LAI、种子和上游Schema仍参与相等比较。"""
    p = load_config(DEFAULT_CONFIG)
    name = "config/params.yaml"
    baseline = upstream_projection(name, yaml.safe_dump(p))
    p["infer"]["year_score_bootstrap"]["repetitions"] += 1
    assert upstream_projection(name, yaml.safe_dump(p)) == baseline
    p["lai"]["annual_time_cover_min"] = .5
    assert upstream_projection(name, yaml.safe_dump(p)) != baseline
    schema = load_config(DEFAULT_CONFIG.parent / "schema_registry.yaml")
    name = "config/schema_registry.yaml"
    baseline = upstream_projection(name, yaml.safe_dump(schema))
    schema["tables"]["q1_recovery_risk"]["columns"].append("test")
    assert upstream_projection(name, yaml.safe_dump(schema)) == baseline
    schema["tables"]["event_exposure"]["columns"].append("test")
    assert upstream_projection(name, yaml.safe_dump(schema)) != baseline


def test_inherited_source_chain_and_tamper(tmp_path):
    """允许从继承别名再继承，沿链发现回执被改写。"""
    p = load_config(DEFAULT_CONFIG)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    def save(path, row):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row), encoding="utf-8")
    original = dict(run_id="original",status="passed", output_files=[])
    source = tmp_path / "logs/source/module_io_M6.json"
    save(source, original)
    save(tmp_path / p["output"]["frozen"] / "downstream/source/M6/module_io.json", original)
    wrapper = dict(run_id="wrapper",source_run_id="original",status="passed",output_files=[],
        execution_mode="inherited_readonly",input_files=[dict(path=source.relative_to(tmp_path).as_posix(),sha256=digest(source))])
    target = tmp_path / "logs/target/module_io_M6.json"
    save(target, wrapper)
    assert validate_receipt_chain(tmp_path, target, "M6", p, digest) == wrapper
    source.write_text("{}",encoding="utf-8")
    with pytest.raises(ValueError, match="哈希"):
        validate_receipt_chain(tmp_path, target, "M6", p, digest)


def test_block_scaling_uses_same_origin():
    """50km聚合到100/200km需保持同原点，负坐标用floor。"""
    p = load_config(DEFAULT_CONFIG)
    grid = [dict(grid_id=str(i),lon=102+i*.4,lat=34+i*.2) for i in range(30)]
    maps = {size:fixed_blocks(grid,[102,34,115,41],size,p) for size in (50,100,200)}
    for g in maps[50]:
        a = [int(x) for x in maps[50][g].split(":")]
        assert maps[100][g] == ":".join(str(x//2) for x in a)
        assert maps[200][g] == ":".join(str(x//4) for x in a)


def test_only_progress_statements_are_compatible():
    """只允许无副作用进度事件差异，上游计算或事件参数副作用均拒绝。"""
    from workflow.inherit_upstream import progress_only_change
    old = "def f(progress, path):\n    x = 1\n    emit(progress, 'M1', '读取')\n    return x\n"
    new = "def f(progress, path):\n    x = 1\n    emit(progress, 'M1', '读取', path=path)\n    emit(progress, 'M1', '完成')\n    return x\n"
    assert progress_only_change(old, new)
    assert not progress_only_change(old, new.replace('x = 1', 'x = 2'))
    assert not progress_only_change(old, new.replace('path=path', 'path=do_work()'))
