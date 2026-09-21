"""任务结构契约。

依据：docs/08 §3.1「统一任务抽象」。
这是监控路径与交互路径规范化后的**同一个**结构；下游不感知 trigger。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .enums import Depth, Intent, Priority, TaskStatus, Trigger


class Budget(BaseModel):
    """任务预算（docs/08 §3.1）。"""

    model_config = ConfigDict(extra="forbid")

    deadline_ms: int = Field(..., gt=0, description="端到端截止时间（毫秒）")
    budget_tokens: int = Field(..., ge=0, description="token 预算上限")
    max_agents: int = Field(..., gt=0, description="参与执行的最大智能体数")


class Scope(BaseModel):
    """作用范围（docs/08 §3.1）。至少指定一种范围。"""

    model_config = ConfigDict(extra="forbid")

    span_ids: list[str] = Field(default_factory=list, description="区段集合")
    line_ids: list[str] = Field(default_factory=list, description="线路集合")
    municipalities: list[str] = Field(default_factory=list, description="地市集合")

    @property
    def is_empty(self) -> bool:
        return not (self.span_ids or self.line_ids or self.municipalities)


class Task(BaseModel):
    """统一任务抽象（docs/08 §3.1）。

    NOTE: `trigger` 仅用于审计、优先级推导与权限判定（actor=system），
    **下游执行阶段不得据此分支**（docs/08 §3.3）。唯二允许依据 trigger 分支的
    位置是深度路由器与产出路由器（docs/08 §10）。
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    trace_id: str
    trigger: Trigger
    trigger_ref: str | None = Field(
        default=None, description="触发源引用：事件 ID / 定时任务 ID / 会话 ID"
    )
    scope: Scope
    intent: Intent
    params: dict[str, Any] = Field(default_factory=dict)
    depth: Depth = Field(default=Depth.L1, description="执行深度上限")
    priority: Priority = Priority.NORMAL
    budget: Budget
    actor: str = Field(..., description="发起身份：用户 ID 或 'system'")
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="强制要求，如 {'must_use_skills': [...], 'require_manual_signoff': true}",
    )
    status: TaskStatus = TaskStatus.CREATED


class TaskStep(BaseModel):
    """任务步骤（表 task_step 的契约视图，docs/05 §4）。"""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    task_id: str
    node_id: str
    capability: str
    agent_id: str
    status: TaskStatus = TaskStatus.CREATED
    attempt: int = Field(default=1, ge=1)
    message_id: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
