"""M0 验收测试（docs/11 §3.4 五条）。

| # | 验收项 | 本文件对应测试 |
|---|---|---|
| 1 | `make check` 可运行并输出注册数量 | test_acceptance_1_registry_loads_and_reports |
| 2 | 技能缺必填字段 → 启动被拒，指出文件与字段 | test_acceptance_2_missing_required_field |
| 3 | 能力模板引用不存在的能力 → 加载被拒并指出位置 | test_acceptance_3_unknown_capability_reference |
| 4 | Agent Card 引用未授权技能 → 加载被拒 | test_acceptance_4_unauthorized_skill_reference |
| 5 | `make test` 全部通过 | 由本文件整体体现 |
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from memory.store.schema import TABLES, create_all, create_engine_for
from runtime.registry import (
    Registry,
    SchemaValidationError,
    UnknownReferenceError,
)


# ---------------------------------------------------------------- 验收项 1
def test_acceptance_1_registry_loads_and_reports(registry: Registry) -> None:
    """`make check` 可运行：输出「已注册 N 个智能体 / M 个技能 / K 个能力模板」。"""
    summary = registry.summary()
    assert summary == {
        "agents": 2,
        "skills": 3,
        "capabilities": 8,
        "templates": 1,
    }
    line = registry.report_line()
    assert "2 个智能体" in line
    assert "3 个技能" in line
    assert "1 个能力模板" in line


def test_acceptance_1_min_tables_created() -> None:
    """最小表集可建表（docs/11 §3.3）。"""
    engine = create_engine_for("sqlite:///:memory:")
    names = create_all(engine)
    assert len(names) == 11
    assert set(names) == {t.name for t in TABLES}
    # 关键表必须在
    for required in (
        "memory_item",
        "memory_edge",
        "memory_access_log",
        "message_log",
        "skill_call_log",
        "task",
        "task_step",
        "trace_snapshot",
        "plan_record",
        "replan_record",
        "plan_rejection",
    ):
        assert required in names


# ---------------------------------------------------------------- 验收项 2
def _edit_yaml(path: Path, mutate) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_acceptance_2_missing_required_field(tmp_config: Path) -> None:
    """技能缺必填字段 → 启动被拒绝，错误信息指出文件与字段。"""
    skills_file = tmp_config / "skills_registry.yaml"

    def drop_owner_agents(data: dict) -> None:
        del data["skills"][0]["owner_agents"]

    _edit_yaml(skills_file, drop_owner_agents)

    with pytest.raises(SchemaValidationError) as excinfo:
        Registry.load(tmp_config)

    message = str(excinfo.value)
    assert "skills_registry.yaml" in message       # 指出文件
    assert "owner_agents" in message               # 指出字段
    assert excinfo.value.source_file is not None
    assert excinfo.value.field is not None


def test_acceptance_2_missing_skill_id(tmp_config: Path) -> None:
    """技能缺 skill_id → 同样被拒。"""
    skills_file = tmp_config / "skills_registry.yaml"

    def drop_skill_id(data: dict) -> None:
        del data["skills"][1]["skill_id"]

    _edit_yaml(skills_file, drop_skill_id)

    with pytest.raises(SchemaValidationError) as excinfo:
        Registry.load(tmp_config)
    assert "skills_registry.yaml" in str(excinfo.value)


def test_acceptance_2_invalid_skill_id_pattern(tmp_config: Path) -> None:
    """技能 id 不符合「分组前缀 + 名称」规范 → 被拒。"""
    skills_file = tmp_config / "skills_registry.yaml"

    def rename(data: dict) -> None:
        data["skills"][0]["skill_id"] = "CalcIcingLoad"   # 缺分组前缀 / 驼峰

    _edit_yaml(skills_file, rename)

    with pytest.raises(SchemaValidationError) as excinfo:
        Registry.load(tmp_config)
    assert "skill_id" in str(excinfo.value)


def test_acceptance_2_nondeterministic_cache_rejected(tmp_config: Path) -> None:
    """非确定性技能不得开启缓存（docs/04 §6 陷阱 7）。"""
    skills_file = tmp_config / "skills_registry.yaml"

    def enable_cache(data: dict) -> None:
        for skill in data["skills"]:
            if skill["skill_id"] == "model.extract_json":
                skill["cache_ttl_s"] = 600

    _edit_yaml(skills_file, enable_cache)

    with pytest.raises(SchemaValidationError) as excinfo:
        Registry.load(tmp_config)
    assert "cache_ttl_s" in str(excinfo.value)


def test_acceptance_2_duplicate_skill_rejected(tmp_config: Path) -> None:
    """同一 skill_id 定义两次 → 被拒。"""
    skills_file = tmp_config / "skills_registry.yaml"

    def duplicate(data: dict) -> None:
        data["skills"].append(dict(data["skills"][0]))

    _edit_yaml(skills_file, duplicate)

    with pytest.raises(Exception) as excinfo:
        Registry.load(tmp_config)
    assert "重复定义" in str(excinfo.value)


# ---------------------------------------------------------------- 验收项 3
def test_acceptance_3_unknown_capability_reference(tmp_config: Path) -> None:
    """能力模板引用不存在的能力 → 加载被拒绝并指出引用位置。"""
    caps_file = tmp_config / "capability_templates.yaml"

    def inject_hallucinated(data: dict) -> None:
        data["templates"][0]["requires"].append(
            {"capability": "quantum_forecast", "mode": "required"}
        )

    _edit_yaml(caps_file, inject_hallucinated)

    with pytest.raises(UnknownReferenceError) as excinfo:
        Registry.load(tmp_config)

    err = excinfo.value
    assert "quantum_forecast" in str(err)
    assert err.source_file and "capability_templates.yaml" in err.source_file
    assert err.field and "risk_assessment" in err.field and "requires" in err.field


def test_acceptance_3_required_capability_without_provider(tmp_config: Path) -> None:
    """required 能力无任何提供者 → 拒绝启动并说明缺失能力（快速失败）。"""
    agents_file = tmp_config / "agents" / "agents.yaml"

    def strip_capability(data: dict) -> None:
        for card in data["agents"]:
            remain = [c for c in card["capabilities"] if c != "data_governance"]
            # AgentCard 要求至少 1 个能力，故替换而非清空
            card["capabilities"] = remain or ["unrelated_capability"]

    _edit_yaml(agents_file, strip_capability)

    with pytest.raises(UnknownReferenceError) as excinfo:
        Registry.load(tmp_config)
    assert "data_governance" in str(excinfo.value)
    assert "无任何智能体提供" in str(excinfo.value)


# ---------------------------------------------------------------- 验收项 4
def test_acceptance_4_unauthorized_skill_reference(tmp_config: Path) -> None:
    """Agent Card 引用未授权（未注册）技能 → 加载被拒绝。"""
    agents_file = tmp_config / "agents" / "agents.yaml"

    def grant_unknown_skill(data: dict) -> None:
        data["agents"][0]["skills"].append("risk.calc_thermal_rating")

    _edit_yaml(agents_file, grant_unknown_skill)

    with pytest.raises(UnknownReferenceError) as excinfo:
        Registry.load(tmp_config)

    err = excinfo.value
    assert "risk.calc_thermal_rating" in str(err)
    assert err.source_file and "agents.yaml" in err.source_file
    assert err.field and "A01_supervisor" in err.field


def test_acceptance_4_skill_owner_must_be_registered(tmp_config: Path) -> None:
    """技能白名单反向悬空（owner_agents 指向未注册智能体）→ 被拒。"""
    skills_file = tmp_config / "skills_registry.yaml"

    def point_to_ghost(data: dict) -> None:
        data["skills"][1]["owner_agents"] = ["A99_ghost"]

    _edit_yaml(skills_file, point_to_ghost)

    with pytest.raises(UnknownReferenceError) as excinfo:
        Registry.load(tmp_config)
    assert "A99_ghost" in str(excinfo.value)


# ---------------------------------------------------------------- 验收项 5
def test_acceptance_5_check_script_runs() -> None:
    """`make check` 入口脚本可执行且退出码为 0。"""
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ)                 # 继承真实解释器环境（sqlalchemy 等依赖）
    env["PYTHONPATH"] = str(root / "src")
    proc = subprocess.run(
        [sys.executable, "scripts/check_registry.py", "--config", "config"],
        cwd=root,
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "已注册 2 个智能体 / 3 个技能 / 1 个能力模板" in proc.stdout
