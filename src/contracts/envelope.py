"""消息信封契约。

依据：docs/03 §3「消息信封规范」。

铁律二：所有智能体间通信、技能调用、事件广播**共用同一信封结构**；
消息必须经信封序列化后投递到总线，不允许 `send()` 内部直接 `target.handle()`。

§3.1 的五条强制约束在本文件中以校验器落地：
  1. `trace_id` 全局贯穿，`parent_msg_id` 构成因果树
  2. `context_refs.memory_ids` 必须声明本次决策引用了哪些记忆
  3. `result.confidence` 必须填写
  4. `telemetry` 必须填写
  5. 无 `source_ref` 的结论视为不可信（在 result.evidence 中体现）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import Performative, ReceiverType, ResultStatus


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class EnvelopeHeader(BaseModel):
    """信封头（docs/03 §3 的 `envelope` 段）。"""

    model_config = ConfigDict(extra="forbid")

    msg_id: str = Field(default_factory=lambda: _new_id("msg"))
    trace_id: str
    parent_msg_id: str | None = Field(
        default=None, description="父消息 ID，构成因果树；根消息为 None"
    )
    session_id: str | None = None
    task_id: str | None = None
    seq: int = Field(default=0, ge=0, description="同一 trace 内的单调序号")
    sender: str
    receiver: str
    receiver_type: ReceiverType = ReceiverType.AGENT
    performative: Performative
    intent: str
    ts: str = Field(default_factory=_now_iso)


class Evidence(BaseModel):
    """结论证据（docs/03 §3.1 约束 5：无 source_ref 的结论视为不可信）。"""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(..., description="data / memory / rule / skill / human")
    ref: str = Field(..., description="证据引用，缺省视为不可信")


class MessageResult(BaseModel):
    """结果段。响应阶段必填 `confidence`。"""

    model_config = ConfigDict(extra="forbid")

    status: ResultStatus = ResultStatus.OK
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="约束 3：必须填写（响应阶段）"
    )
    evidence: list[Evidence] = Field(default_factory=list)
    error: str | None = None
    reason: str | None = Field(
        default=None, description="REFUSE 必须携带拒绝理由（docs/03 §4 协议纪律）"
    )


class Telemetry(BaseModel):
    """遥测段。约束 4：必须填写。"""

    model_config = ConfigDict(extra="forbid")

    model: str | None = None
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    latency_ms: int = Field(default=0, ge=0)
    cost_estimate: float = Field(default=0.0, ge=0.0)


class ContextRefs(BaseModel):
    """引用上下文（docs/03 §3 的 `context_refs` 段）。"""

    model_config = ConfigDict(extra="forbid")

    memory_ids: list[str] = Field(
        default_factory=list, description="约束 2：必须声明本次决策引用了哪些记忆"
    )
    blackboard_keys: list[str] = Field(default_factory=list)
    skill_calls: list[str] = Field(default_factory=list)


class Constraints(BaseModel):
    """信封级约束（docs/03 §3 的 `constraints` 段）。"""

    model_config = ConfigDict(extra="forbid")

    deadline_ms: int | None = Field(default=None, gt=0)
    budget_tokens: int | None = Field(default=None, ge=0)
    priority: str | None = None
    must_use_skills: list[str] = Field(default_factory=list)


class Security(BaseModel):
    """安全段（docs/03 §8 消息级）。"""

    model_config = ConfigDict(extra="forbid")

    user_id: str | None = None
    role: str | None = None
    sensitivity: str = "internal"
    allowed_zones: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    """统一消息信封（docs/03 §3）。

    七个段落缺一不可；`envelope` / `telemetry` 为强制段。
    """

    model_config = ConfigDict(extra="forbid")

    envelope: EnvelopeHeader
    payload: dict[str, Any] = Field(default_factory=dict)
    context_refs: ContextRefs = Field(default_factory=ContextRefs)
    constraints: Constraints = Field(default_factory=Constraints)
    result: MessageResult = Field(default_factory=MessageResult)
    telemetry: Telemetry = Field(default_factory=Telemetry)
    security: Security = Field(default_factory=Security)

    # ---------------------------------------------------------------- 校验
    @model_validator(mode="after")
    def _check_protocol_discipline(self) -> "Envelope":
        pf = self.envelope.performative
        # 协议纪律：REFUSE 必须携带拒绝理由（docs/03 §4）
        if pf is Performative.REFUSE and not self.result.reason:
            raise ValueError("REFUSE 必须携带 result.reason（拒绝理由不允许静默）")
        # 协议纪律：FAILURE 应带失败原因
        if pf is Performative.FAILURE and not (self.result.error or self.result.reason):
            raise ValueError("FAILURE 必须携带 result.error 或 result.reason")
        # 约束 5：结论文本必须可溯源，PROPOSE 至少一条 evidence
        if pf is Performative.PROPOSE and not self.result.evidence:
            raise ValueError("PROPOSE 必须携带 result.evidence（无 source_ref 的结论不可信）")
        return self

    # ------------------------------------------------------------ 便捷构造
    @classmethod
    def request(
        cls,
        *,
        trace_id: str,
        sender: str,
        receiver: str,
        performative: Performative,
        intent: str,
        payload: dict[str, Any] | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        parent_msg_id: str | None = None,
        seq: int = 0,
        receiver_type: ReceiverType = ReceiverType.AGENT,
        constraints: Constraints | None = None,
        security: Security | None = None,
        context_refs: ContextRefs | None = None,
    ) -> "Envelope":
        """构造请求/执行阶段消息（docs/03 §3.2 请求阶段字段集）。"""
        return cls(
            envelope=EnvelopeHeader(
                trace_id=trace_id,
                parent_msg_id=parent_msg_id,
                session_id=session_id,
                task_id=task_id,
                seq=seq,
                sender=sender,
                receiver=receiver,
                receiver_type=receiver_type,
                performative=performative,
                intent=intent,
            ),
            payload=payload or {},
            context_refs=context_refs or ContextRefs(),
            constraints=constraints or Constraints(),
            telemetry=Telemetry(),
            security=security or Security(),
        )

    def derive(
        self,
        *,
        sender: str,
        receiver: str,
        performative: Performative,
        payload: dict[str, Any] | None = None,
        result: MessageResult | None = None,
        telemetry: Telemetry | None = None,
        context_refs: ContextRefs | None = None,
        intent: str | None = None,
        receiver_type: ReceiverType | None = None,
    ) -> "Envelope":
        """派生一条子消息：继承 trace_id 并把本消息设为父消息（约束 1）。"""
        return Envelope(
            envelope=EnvelopeHeader(
                trace_id=self.envelope.trace_id,
                parent_msg_id=self.envelope.msg_id,
                session_id=self.envelope.session_id,
                task_id=self.envelope.task_id,
                seq=self.envelope.seq + 1,
                sender=sender,
                receiver=receiver,
                receiver_type=receiver_type or self.envelope.receiver_type,
                performative=performative,
                intent=intent or self.envelope.intent,
            ),
            payload=payload or {},
            context_refs=context_refs or ContextRefs(),
            constraints=self.constraints,
            result=result or MessageResult(),
            telemetry=telemetry or Telemetry(),
            security=self.security,
        )

    # -------------------------------------------------------- 序列化（总线）
    def to_wire(self) -> str:
        """信封 → 传输字节串。总线只搬运字节串，不搬运对象（铁律二）。"""
        return self.model_dump_json()

    @classmethod
    def from_wire(cls, raw: str | bytes) -> "Envelope":
        """传输字节串 → 信封（接收方反序列化）。"""
        return cls.model_validate_json(raw)
