"""契约层单测：验证 M0 冻结的协议结构符合 docs/01、02、03、04、08、09 的定义。

重点验证「五条强制约束」与「协议纪律」被结构性保证（而非靠约定）。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts import (
    PERFORMATIVE_RESPONSES,
    AgentCard,
    Budget,
    CapabilityRequirement,
    CapabilitySpec,
    CapabilityTemplate,
    ContextRefs,
    Depth,
    Envelope,
    EnvelopeHeader,
    Evidence,
    Intent,
    MemoryItem,
    MessageResult,
    ModelBinding,
    PlanRejectionReason,
    PlanRejection,
    RequirementMode,
    ResultStatus,
    Scope,
    Security,
    SkillSpec,
    Task,
    Telemetry,
    Trigger,
    ValidationResult,
)
from contracts.enums import MemoryScope, MemoryStatus, MemoryType, Performative


# ============================================================ docs/08 §3.1 Task
def test_task_fields_match_docs_08_section_3_1() -> None:
    """Task 字段与 docs/08 §3.1 一致，且 trigger 仅供审计不驱动下游。"""
    task = Task(
        task_id="tsk_1",
        trace_id="trc_1",
        trigger=Trigger.EVENT,
        trigger_ref="alert_001",
        scope=Scope(span_ids=["sp_1"]),
        intent=Intent.RISK_ASSESSMENT,
        params={"disaster_types": ["icing"]},
        depth=Depth.L1,
        budget=Budget(deadline_ms=30000, budget_tokens=8000, max_agents=8),
        actor="system",
    )
    assert task.status.value == "created"
    assert set(Task.model_fields) >= {
        "task_id", "trace_id", "trigger", "trigger_ref", "scope", "intent",
        "params", "depth", "priority", "budget", "actor", "constraints",
    }


def test_scope_can_be_empty_detection() -> None:
    assert Scope().is_empty is True
    assert Scope(line_ids=["L1"]).is_empty is False


def test_task_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        Task(
            task_id="t", trace_id="tr", trigger=Trigger.USER, scope=Scope(line_ids=["L"]),
            intent=Intent.POINT_QUERY,
            budget=Budget(deadline_ms=1000, budget_tokens=10, max_agents=1),
            actor="u_002", unknown_field=1,
        )


# =================================================== docs/03 §3 信封与五条约束
def _minimal_envelope(**overrides) -> Envelope:
    base = dict(
        envelope=EnvelopeHeader(
            trace_id="trc_1",
            sender="A01_supervisor",
            receiver="A03_data_steward",
            performative=Performative.REQUEST,
            intent="risk_assessment",
        ),
        telemetry=Telemetry(model="stub-light"),
    )
    base.update(overrides)
    return Envelope(**base)


def test_envelope_has_seven_sections() -> None:
    env = _minimal_envelope()
    assert set(Envelope.model_fields) == {
        "envelope", "payload", "context_refs", "constraints",
        "result", "telemetry", "security",
    }
    assert set(EnvelopeHeader.model_fields) >= {
        "msg_id", "trace_id", "parent_msg_id", "session_id", "task_id", "seq",
        "sender", "receiver", "receiver_type", "performative", "intent", "ts",
    }


def test_constraint_5_propose_must_carry_evidence() -> None:
    """约束 5：无 source_ref 的结论视为不可信 → PROPOSE 必须带 evidence。"""
    with pytest.raises(ValidationError) as excinfo:
        _minimal_envelope(
            envelope=EnvelopeHeader(
                trace_id="trc_1", sender="A07", receiver="A13",
                performative=Performative.PROPOSE, intent="risk_ranking_result",
            ),
            result=MessageResult(status=ResultStatus.OK, confidence=0.8),
        )
    assert "evidence" in str(excinfo.value)


def test_propose_with_evidence_ok() -> None:
    env = _minimal_envelope(
        envelope=EnvelopeHeader(
            trace_id="trc_1", sender="A07", receiver="A13",
            performative=Performative.PROPOSE, intent="risk_ranking_result",
        ),
        result=MessageResult(
            status=ResultStatus.OK,
            confidence=0.81,
            evidence=[Evidence(type="data", ref="meteo_obs:icing:001")],
        ),
        context_refs=ContextRefs(memory_ids=["mem_1"]),
    )
    assert env.result.confidence == 0.81
    assert env.context_refs.memory_ids == ["mem_1"]


def test_protocol_discipline_refuse_must_carry_reason() -> None:
    """协议纪律：REFUSE 必须携带拒绝理由，不允许静默拒绝。"""
    with pytest.raises(ValidationError) as excinfo:
        _minimal_envelope(
            envelope=EnvelopeHeader(
                trace_id="trc_1", sender="A03", receiver="A01",
                performative=Performative.REFUSE, intent="risk_assessment",
            ),
        )
    assert "REFUSE" in str(excinfo.value)


def test_protocol_discipline_failure_must_carry_error() -> None:
    with pytest.raises(ValidationError):
        _minimal_envelope(
            envelope=EnvelopeHeader(
                trace_id="trc_1", sender="A03", receiver="A01",
                performative=Performative.FAILURE, intent="risk_assessment",
            ),
        )


def test_performative_response_sets_are_defined() -> None:
    """docs/03 §4：每个 performative 有确定的响应集合。"""
    assert Performative.CONFIRM in PERFORMATIVE_RESPONSES[Performative.REQUEST]
    assert Performative.FAILURE in PERFORMATIVE_RESPONSES[Performative.REQUEST]
    assert Performative.REFUSE in PERFORMATIVE_RESPONSES[Performative.REQUEST]
    assert PERFORMATIVE_RESPONSES[Performative.INFORM] == frozenset()
    assert Performative.ACCEPT in PERFORMATIVE_RESPONSES[Performative.PROPOSE]


def test_envelope_derive_keeps_trace_and_sets_parent() -> None:
    """约束 1：trace_id 全局贯穿，parent_msg_id 构成因果树。"""
    root = _minimal_envelope()
    child = root.derive(
        sender="A03_data_steward", receiver="A01_supervisor",
        performative=Performative.CONFIRM,
    )
    assert child.envelope.trace_id == root.envelope.trace_id
    assert child.envelope.parent_msg_id == root.envelope.msg_id
    assert child.envelope.seq == root.envelope.seq + 1


def test_envelope_wire_roundtrip() -> None:
    """铁律二的基础：信封可序列化 → 传输 → 反序列化，不传对象。"""
    env = _minimal_envelope(
        security=Security(user_id="u_002", role="specialist", allowed_zones=["zone_a", "all"]),
    )
    raw = env.to_wire()
    assert isinstance(raw, str)
    restored = Envelope.from_wire(raw)
    assert restored.envelope.msg_id == env.envelope.msg_id
    assert restored.security.user_id == "u_002"
    assert restored.model_dump() == env.model_dump()


# ==================================================== docs/04 §2 技能声明字段
def test_skill_spec_fields_match_docs_04_section_2() -> None:
    spec = SkillSpec(
        skill_id="risk.calc_icing_load",
        name="覆冰荷载估算",
        description="依据覆冰厚度估算荷载；无观测数据时不适用。",
        category="risk",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        deterministic=True,
        owner_agents=["A01_supervisor"],
        impl_mode="formula",
        audit_level="summary",
        version="v1.0",
        cache_ttl_s=300,
    )
    assert spec.group == "risk"
    assert set(SkillSpec.model_fields) >= {
        "skill_id", "name", "description", "category", "input_schema", "output_schema",
        "deterministic", "owner_agents", "permission_scope", "rate_limit", "timeout_ms",
        "impl_mode", "audit_level", "version",
    }


def test_skill_id_requires_group_prefix() -> None:
    with pytest.raises(ValidationError):
        SkillSpec(
            skill_id="icing_load", name="x", description="yyyyyyyy",
            category="risk", input_schema={}, output_schema={},
            deterministic=True, owner_agents=["A1"],
        )


def test_skill_description_must_be_meaningful() -> None:
    """description 过短会让模型选错技能（docs/04 §6 陷阱 2）。"""
    with pytest.raises(ValidationError):
        SkillSpec(
            skill_id="risk.x", name="x", description="短",
            category="risk", input_schema={}, output_schema={},
            deterministic=True, owner_agents=["A1"],
        )


# ================================================== docs/01 §3 Agent Card 字段
def test_agent_card_fields_match_docs_01_section_3() -> None:
    card = AgentCard(
        agent_id="A01_supervisor",
        name="主控调度",
        role="编排",
        description="任务分解与调度；不在我职责内的数值计算不应经过我。",
        capabilities=["orchestration"],
        skills=["model.extract_json"],
        model_binding=ModelBinding.LIGHT,
    )
    assert set(AgentCard.model_fields) >= {
        "agent_id", "name", "role", "description", "capabilities", "skills",
        "input_schema", "output_schema", "model_binding", "memory_access",
        "max_concurrency", "cost_profile", "permission_scope", "failure_policy", "version",
    }


def test_agent_card_requires_at_least_one_capability() -> None:
    with pytest.raises(ValidationError):
        AgentCard(
            agent_id="A99", name="x", role="执行", description="yyyyyyyyyy",
            capabilities=[], skills=[],
        )


def test_failure_policy_retry_capped_at_one() -> None:
    """docs/03 §7.2：重试次数刻意压低，最多 1 次。"""
    with pytest.raises(ValidationError):
        AgentCard(
            agent_id="A99", name="x", role="执行", description="yyyyyyyyyy",
            capabilities=["c"], failure_policy={"timeout_ms": 1000, "max_retries": 3},
        )


# ================================================ docs/09 §4.2 能力模板契约
def test_required_capability_must_not_have_condition() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CapabilityRequirement(
            capability="data_governance", mode=RequirementMode.REQUIRED,
            when={"depth_gte": "L1"},
        )
    assert "required" in str(excinfo.value)


def test_conditional_capability_must_have_condition() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CapabilityRequirement(
            capability="history_retrieval", mode=RequirementMode.CONDITIONAL,
        )
    assert "when" in str(excinfo.value)


def test_template_rejects_unknown_intent() -> None:
    with pytest.raises(ValidationError):
        CapabilityTemplate(intent="not_an_intent", requires=[{"capability": "x"}])  # type: ignore[arg-type]


def test_capability_spec_declares_inputs_outputs() -> None:
    """docs/09 §5.1：依赖推导的唯一依据是 inputs / outputs 声明。"""
    spec = CapabilitySpec(
        capability="risk_scoring",
        inputs=["meteo_features", "candidate_spans", "rule_hits"],
        outputs=["risk_ranking"],
    )
    assert "rule_hits" in spec.inputs
    assert spec.outputs == ["risk_ranking"]


# ================================================ docs/09 §7 校验器与拒绝记录
def test_validation_result_must_give_reason_on_failure() -> None:
    with pytest.raises(ValidationError):
        ValidationResult(passed=False)
    ok = ValidationResult.ok()
    assert ok.passed and ok.reason is None
    bad = ValidationResult.reject(
        PlanRejectionReason.UNKNOWN_REFERENCE, "模板引用了不存在的能力", ["quantum_forecast"]
    )
    assert bad.reason is PlanRejectionReason.UNKNOWN_REFERENCE
    assert bad.offending_refs == ["quantum_forecast"]


def test_plan_rejection_reasons_cover_docs_09_section_7() -> None:
    """校验器八条铁律对应的拒绝原因必须齐全。"""
    assert len(list(PlanRejectionReason)) == 8


# =================================================== docs/02 §4.1 记忆硬约束
def test_memory_item_requires_source_ref() -> None:
    """硬约束：无来源的记忆不允许落库（docs/02 §3.1 第 7 步）。"""
    with pytest.raises(ValidationError) as excinfo:
        MemoryItem(
            memory_id="mem_1", scope_type=MemoryScope.GLOBAL, mem_type=MemoryType.SEMANTIC,
            title="覆冰阈值", content="覆冰启动阈值为 12mm",
            source_type="task", source_ref="", confidence=0.9,
        )
    assert "source_ref" in str(excinfo.value)


def test_memory_item_user_scope_requires_owner() -> None:
    """用户记忆必须按 user_id 隔离（docs/02 §2.1）。"""
    with pytest.raises(ValidationError) as excinfo:
        MemoryItem(
            memory_id="mem_2", scope_type=MemoryScope.USER, mem_type=MemoryType.USER_PREFERENCE,
            title="偏好", content="偏好要点式输出",
            source_type="approval", source_ref="trc_1", confidence=0.8,
        )
    assert "owner_user_id" in str(excinfo.value)


def test_memory_item_ok_and_status_enum() -> None:
    item = MemoryItem(
        memory_id="mem_3", scope_type=MemoryScope.USER, scope_id="u_002",
        owner_user_id="u_002", mem_type=MemoryType.USER_PREFERENCE,
        title="偏好", content="偏好要点式输出",
        source_type="approval", source_ref="trc_1", confidence=0.8,
    )
    assert item.status is MemoryStatus.ACTIVE
    assert {s.value for s in MemoryStatus} == {
        "active", "archived", "disputed", "superseded", "rejected",
    }


def test_plan_rejection_model_dump_has_offending_refs() -> None:
    rec = PlanRejection(
        rejection_id="rej_1", task_id="tsk_1", trace_id="trc_1",
        reason=PlanRejectionReason.MISSING_REQUIRED_CAPABILITY,
        detail="缺少 risk_scoring 的提供者", offending_refs=["risk_scoring"],
    )
    assert rec.model_dump()["offending_refs"] == ["risk_scoring"]
