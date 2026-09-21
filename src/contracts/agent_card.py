"""Agent Card 契约。

依据：docs/01 §3「Agent Card 规范」。

卡片是智能体的「身份证 + 能力说明 + 资源画像」，声明式注册、可扫描、可校验、
可展示、可热更新 —— 而非代码继承。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import AgentStatus, ModelBinding, PermissionScope


class MemoryAccess(BaseModel):
    """记忆读写权限（docs/01 §3）。越权读写被拒。"""

    model_config = ConfigDict(extra="forbid")

    read: list[str] = Field(default_factory=list, description="可读作用域")
    write: list[str] = Field(default_factory=list, description="可写作用域")


class CostProfile(BaseModel):
    """预估开销画像，用于预算控制（docs/01 §3）。"""

    model_config = ConfigDict(extra="forbid")

    est_tokens: int = Field(default=0, ge=0)
    est_latency_ms: int = Field(default=0, ge=0)


class FailurePolicy(BaseModel):
    """失败处置策略（docs/01 §3）。"""

    model_config = ConfigDict(extra="forbid")

    timeout_ms: int = Field(default=30000, gt=0)
    max_retries: int = Field(default=1, ge=0, le=1, description="docs/03 §7.2：最多重试 1 次")
    fallback_to: str | None = Field(default=None, description="降级目标 agent_id")
    can_escalate_to_human: bool = Field(default=True)


class AgentCard(BaseModel):
    """声明式智能体卡片（docs/01 §3）。

    字段与文档表格一一对应，字段名不得随意改动（契约冻结）。
    """

    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(..., pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    name: str
    role: str
    description: str = Field(
        ..., min_length=8, description="供 Supervisor 做智能体选择，需写清何时调用我"
    )
    capabilities: list[str] = Field(
        ..., min_length=1, description="能力标签，用于任务路由匹配（docs/09 §4.3 反向索引来源）"
    )
    skills: list[str] = Field(
        default_factory=list, description="可调用技能白名单，越权调用被拒（铁律三）"
    )
    input_schema: dict = Field(default_factory=dict)
    output_schema: dict = Field(default_factory=dict)
    model_binding: ModelBinding = ModelBinding.NONE
    memory_access: MemoryAccess = Field(default_factory=MemoryAccess)
    max_concurrency: int = Field(default=4, ge=1)
    cost_profile: CostProfile = Field(default_factory=CostProfile)
    permission_scope: PermissionScope = PermissionScope.OPERATOR
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    version: str = Field(default="v0.1")
    status: AgentStatus = AgentStatus.ENABLED
    min_depth: str = Field(
        default="L0",
        description="该智能体要求的最低执行深度（docs/09 §4.3 第 3 条过滤规则）",
    )

    # 以下字段为运行期装载信息，不参与配置校验
    source_file: str | None = Field(default=None, exclude=True)
