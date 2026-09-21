"""能力定义与能力需求模板契约。

依据：docs/09 §4.2（能力需求模板）、§4.3（能力索引）、§5.1（能力的输入输出声明）。

关键设计（docs/09 §4.1）：先推导**能力**，再由能力索引映射到**智能体**。
能力是稳定抽象，智能体是其实现。这让模板可审阅、可 diff、可回归。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import Depth, Intent, RequirementMode


class CapabilitySpec(BaseModel):
    """能力定义（docs/09 §5.1）。

    依赖推导的唯一依据：`A.outputs ∩ B.inputs ≠ ∅` 则 B 依赖 A。
    """

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(..., description="能力标识，如 risk_scoring")
    description: str = ""
    inputs: list[str] = Field(default_factory=list, description="声明的输入产物")
    outputs: list[str] = Field(default_factory=list, description="声明的输出产物")
    is_terminal: bool = Field(
        default=False, description="是否为终态产出（用于图剪枝，docs/09 §5.2「最小」）"
    )


class Condition(BaseModel):
    """条件能力的启用条件（docs/09 §4.2）。"""

    model_config = ConfigDict(extra="forbid")

    depth_gte: Depth | None = Field(default=None, description="深度不低于此值则启用")
    has_artifact: str | None = Field(default=None, description="存在某产物则启用")
    has_capability: str | None = Field(default=None, description="已入选某能力则启用")


class CapabilityRequirement(BaseModel):
    """模板中的一条能力需求（docs/09 §4.2）。"""

    model_config = ConfigDict(extra="forbid")

    capability: str
    mode: RequirementMode = RequirementMode.REQUIRED
    when: Condition | None = Field(
        default=None, description="仅 conditional / optional 允许携带条件"
    )

    @model_validator(mode="after")
    def _check_mode(self) -> "CapabilityRequirement":
        if self.mode is RequirementMode.REQUIRED and self.when is not None:
            raise ValueError("required 能力不允许携带 when 条件（必须无条件纳入）")
        if self.mode is not RequirementMode.REQUIRED and self.when is None:
            raise ValueError(
                f"{self.mode.value} 能力必须携带 when 条件，否则无法判定启用时机"
            )
        return self


class CapabilityTemplate(BaseModel):
    """能力需求模板（docs/09 §4.2）。**配置而非代码**。"""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    description: str = ""
    requires: list[CapabilityRequirement] = Field(..., min_length=1)
    terminal_output: str | None = Field(
        default=None,
        description="终态产物，供校验器第 8 条比对（docs/09 §7）",
    )


class CapabilityProvider(BaseModel):
    """能力的提供者（docs/09 §4.3）。"""

    model_config = ConfigDict(extra="forbid")

    agent: str
    priority: int = Field(default=1, ge=1, description="越小越优先")
    version: str = "v1.0"


class AgentCapabilityIndex(BaseModel):
    """Agent Registry 的能力 → 智能体反向索引（docs/09 §4.3）。

    由 Agent Card 的 `capabilities` 字段**自动构建**，不是第二份配置源。
    """

    model_config = ConfigDict(extra="forbid")

    capability: str
    providers: list[CapabilityProvider] = Field(default_factory=list)

    def at_priority(self) -> list[CapabilityProvider]:
        return sorted(self.providers, key=lambda p: (p.priority, p.agent))
