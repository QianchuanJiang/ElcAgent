"""执行图与规划记录契约。

依据：docs/09 §8「数据结构」。

铁律一：执行图必须由「意图 → 能力需求模板 → 能力索引查表 → 依赖推导 →
拓扑排序」动态生成，不得写死。本文件的 `ExecutionGraph` 是这条链路的输出。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import Depth, Intent, PlanRejectionReason


class GraphNode(BaseModel):
    """执行图节点（docs/09 §8.1）。"""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    capability: str
    agent_id: str
    depends_on: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    condition: dict[str, Any] | None = Field(default=None, description="条件能力专用")
    budget: dict[str, Any] = Field(
        default_factory=dict, description="该节点超时与 token 上限"
    )
    parallel_group: str | None = None
    fallback: str | None = Field(default=None, description="降级目标 agent_id")
    depth: Depth = Depth.L1


class DependencyEdge(BaseModel):
    """依赖边。**每条边必须可解释**（docs/09 §5.2）。

    `via` 记录产生该边的输入输出交集，任何人可复核。
    """

    model_config = ConfigDict(extra="forbid")

    from_node: str
    to_node: str
    via: list[str] = Field(..., min_length=1, description="inputs ∩ outputs 的交集")


class ExecutionGraph(BaseModel):
    """执行图（plan_record 的核心产出）。"""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    intent: Intent
    depth: Depth
    nodes: list[GraphNode] = Field(..., min_length=1)
    edges: list[DependencyEdge] = Field(default_factory=list)
    parallel_groups: dict[str, list[str]] = Field(
        default_factory=dict, description="parallel_group -> node_ids"
    )
    terminal_output: str | None = None

    def node(self, node_id: str) -> GraphNode | None:
        return next((n for n in self.nodes if n.node_id == node_id), None)

    @property
    def node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes]

    def describe_label(self) -> str:
        """图的紧凑指纹，用于 M2「同一意图不同深度的图可 diff」。"""
        return f"{self.intent.value}@{self.depth.value}:" + ",".join(
            sorted(n.capability for n in self.nodes)
        )


class ReplanTrigger(BaseModel):
    """重规划触发原因（docs/09 §6.1）。"""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(..., description="node_failure / node_degraded / precondition_false / budget_exhausted")
    node_id: str
    detail: str = ""


class PlanRecord(BaseModel):
    """每次规划的输入与输出（docs/09 §8.2）。"""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    task_id: str
    trace_id: str
    intent: Intent
    depth: Depth
    scope_summary: dict[str, Any] = Field(default_factory=dict)
    selected_agents: list[str] = Field(default_factory=list)
    graph: ExecutionGraph
    rationale: dict[str, Any] = Field(
        default_factory=dict, description="入选依据：每条能力为什么被启用/跳过"
    )


class ReplanRecord(BaseModel):
    """重规划记录（docs/09 §6.4 必须留痕）。"""

    model_config = ConfigDict(extra="forbid")

    replan_id: str
    task_id: str
    trace_id: str
    trigger: ReplanTrigger
    impact_scope: list[str] = Field(default_factory=list, description="沿依赖边正向可达的下游节点")
    replacement: dict[str, Any] = Field(default_factory=dict)
    graph_before: list[str] = Field(default_factory=list)
    graph_after: list[str] = Field(default_factory=list)
    attempt: int = Field(default=1, ge=1, le=1, description="docs/09 §6.4：最多重规划 1 次")
    resolved: bool = False


class PlanRejection(BaseModel):
    """被校验器拒绝的图及原因（docs/09 §7、§8.2）。

    开发期价值极高：直接暴露模型幻觉与配置错误。
    """

    model_config = ConfigDict(extra="forbid")

    rejection_id: str
    task_id: str
    trace_id: str
    reason: PlanRejectionReason
    detail: str
    offending_refs: list[str] = Field(
        default_factory=list, description="违规引用，如不存在的能力或智能体"
    )
    at_step: str = Field(default="validator", description="拒绝发生在链路哪一步")


class ValidationResult(BaseModel):
    """契约校验器返回。"""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    reason: PlanRejectionReason | None = None
    detail: str = ""
    offending_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "ValidationResult":
        if not self.passed and self.reason is None:
            raise ValueError("校验失败必须给出拒绝原因")
        return self

    @classmethod
    def ok(cls) -> "ValidationResult":
        return cls(passed=True)

    @classmethod
    def reject(
        cls,
        reason: PlanRejectionReason,
        detail: str,
        offending_refs: list[str] | None = None,
    ) -> "ValidationResult":
        return cls(
            passed=False,
            reason=reason,
            detail=detail,
            offending_refs=offending_refs or [],
        )
