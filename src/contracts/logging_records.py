"""日志表契约：message_log / skill_call_log / trace_snapshot / task_step 等。

依据：docs/03 §10（通信数据模型）、docs/05 §4（表清单）、docs/09 §8.2。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import FallbackLevel, ResultStatus


class MessageLogRecord(BaseModel):
    """message_log（docs/03 §10）。每条消息完整落库。"""

    model_config = ConfigDict(extra="forbid")

    msg_id: str
    trace_id: str
    parent_msg_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None
    seq: int = 0
    sender: str
    receiver: str
    performative: str
    intent: str
    payload_digest: str = ""
    context_memory_ids: list[str] = Field(default_factory=list)
    context_skill_calls: list[str] = Field(default_factory=list)
    status: ResultStatus = ResultStatus.OK
    confidence: float | None = None
    model_name: str | None = None
    model_profile: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    security_role: str | None = None
    timestamp: str | None = None


class SkillCallLogRecord(BaseModel):
    """skill_call_log（docs/03 §10）。带副作用的技能调用据此去重（docs/03 §7.1）。"""

    model_config = ConfigDict(extra="forbid")

    call_id: str
    trace_id: str
    msg_id: str | None = None
    skill_id: str
    skill_version: str = "v1.0"
    caller_agent: str
    input_digest: str = ""
    output_digest: str = ""
    cache_hit: bool = False
    fallback_level: FallbackLevel = FallbackLevel.NORMAL
    latency_ms: int = 0
    status: ResultStatus = ResultStatus.OK
    created_at: str | None = None


class TraceSnapshot(BaseModel):
    """trace_snapshot（docs/03 §10、§9.4 回放）。"""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    trace_id: str
    task_type: str
    started_at: str | None = None
    ended_at: str | None = None
    total_ms: int = 0
    message_seq: list[str] = Field(default_factory=list)
    final_result: dict[str, Any] = Field(default_factory=dict)
    key_metrics: dict[str, Any] = Field(default_factory=dict)


class SkillHealth(BaseModel):
    """技能健康度五指标（docs/04 §5.1）。M5 使用，契约在此先冻结。"""

    model_config = ConfigDict(extra="forbid")

    skill_id: str
    call_count: int = 0
    success_count: int = 0
    p95_latency_ms: int = 0
    cache_hit_count: int = 0
    fallback_count: int = 0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.call_count if self.call_count else 0.0

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hit_count / self.call_count if self.call_count else 0.0
