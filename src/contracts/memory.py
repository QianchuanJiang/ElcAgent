"""记忆契约。

依据：docs/02 §4.1（memory_item）、§4.2（配套表）、§6（与智能体的接口约定）。

硬约束（docs/02 §3.1 第 7 步）：长期记忆**必须携带 `source_ref` 与 `confidence`**，
无来源的记忆不允许落库。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import MemoryScope, MemoryStatus, MemoryType, RetrievalMode


class MemoryItem(BaseModel):
    """记忆主表 memory_item（docs/02 §4.1）。"""

    model_config = ConfigDict(extra="forbid")

    memory_id: str
    scope_type: MemoryScope
    scope_id: str | None = Field(default=None, description="session_id / user_id / org_id")
    mem_type: MemoryType

    title: str = Field(..., max_length=30)
    content: str = Field(..., max_length=500)
    structured_payload: dict[str, Any] = Field(default_factory=dict)

    source_type: str = Field(..., description="task / message / approval / import")
    source_ref: str = Field(..., min_length=1, description="trace_id 或 message_id，必填")
    confidence: float = Field(..., ge=0.0, le=1.0)

    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    access_count: int = Field(default=0, ge=0)
    last_access_at: str | None = None
    decay_score: float = Field(default=1.0, ge=0.0, le=1.0)

    valid_from: str | None = None
    valid_until: str | None = None
    status: MemoryStatus = MemoryStatus.ACTIVE

    sensitivity_level: str = "internal"
    owner_user_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    embedding_ref: str | None = None
    created_at: str | None = None

    @model_validator(mode="after")
    def _check_source(self) -> "MemoryItem":
        # 硬约束：无来源的记忆不允许落库（docs/02 §3.1 第 7 步）
        if not self.source_ref:
            raise ValueError("memory_item 必须携带 source_ref（无来源记忆不允许落库）")
        if self.scope_type is MemoryScope.USER and not self.owner_user_id:
            raise ValueError("scope_type=user 时必须指定 owner_user_id（用户记忆隔离）")
        return self


class MemoryEdge(BaseModel):
    """记忆关系边 memory_edge（docs/02 §4.2）。"""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    from_memory_id: str
    to_memory_id: str
    edge_type: str = Field(..., description="derived_from / contradicts / supersedes / related / supports")
    weight: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = Field(default="", description="建立该边的理由，必留痕")


class MemoryAccessLog(BaseModel):
    """访问日志 memory_access_log（docs/02 §4.2、§4.4）。

    `used_in_output` 区分「被检索到」与「真的被用上」，
    是记忆价值评估的唯一数据来源（docs/10 §6）。
    """

    model_config = ConfigDict(extra="forbid")

    access_id: str
    memory_id: str
    query: str
    caller: str
    scores: dict[str, float] = Field(
        default_factory=dict, description="三路得分 + 融合得分"
    )
    latency_ms: int = Field(default=0, ge=0)
    used_in_output: bool = Field(default=False, description="T-4 阶段回填")
    accessed_at: str | None = None


class MemorySearchRequest(BaseModel):
    """`memory.search` 输入（docs/02 §6）。"""

    model_config = ConfigDict(extra="forbid")

    query: str
    scope_filter: list[MemoryScope] = Field(default_factory=list)
    type_filter: list[MemoryType] = Field(default_factory=list)
    top_k: int = Field(default=6, gt=0)


class MemoryHit(BaseModel):
    """检索命中项，含得分与来源（docs/02 §6）。"""

    model_config = ConfigDict(extra="forbid")

    memory_id: str
    title: str
    content: str
    mem_type: MemoryType
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)


class MemorySearchResult(BaseModel):
    """统一约束：所有读操作返回体必须包含这三个字段（docs/02 §6）。"""

    model_config = ConfigDict(extra="forbid")

    hits: list[MemoryHit] = Field(default_factory=list)
    retrieval_mode: RetrievalMode
    hit_count: int = Field(..., ge=0)
    latency_ms: int = Field(..., ge=0)

    @model_validator(mode="after")
    def _check_count(self) -> "MemorySearchResult":
        if self.hit_count != len(self.hits):
            raise ValueError("hit_count 必须等于 hits 长度")
        return self


class MemoryWriteRequest(BaseModel):
    """`memory.write` 输入（docs/02 §6）。执行智能体本身无长期写权限（docs/10 §4.3）。"""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., max_length=30)
    content: str = Field(..., max_length=500)
    mem_type: MemoryType
    scope_type: MemoryScope
    scope_id: str | None = None
    source_type: str
    source_ref: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)
    structured_payload: dict[str, Any] = Field(default_factory=dict)
