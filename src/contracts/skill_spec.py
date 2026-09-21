"""技能声明契约。

依据：docs/04 §2「技能定义规范」。

铁律三：技能必须注册与鉴权，注册表不能是硬编码字典。
本文件的 `SkillSpec` 是注册表的行结构，字段与 docs/04 §2 表格一一对应。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .enums import AuditLevel, ImplMode, PermissionScope


class RateLimit(BaseModel):
    """单技能独立配额（docs/04 §5）。超限返回失败，**不阻塞主链路**。"""

    model_config = ConfigDict(extra="forbid")

    max_calls: int = Field(..., gt=0, description="窗口内最大调用次数")
    window_s: int = Field(default=60, gt=0, description="窗口长度（秒）")


class SkillSpec(BaseModel):
    """技能声明（docs/04 §2）。"""

    model_config = ConfigDict(extra="forbid")

    skill_id: str = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$",
        description="分组前缀 + 名称，如 risk.calc_icing_load",
    )
    name: str
    description: str = Field(
        ...,
        min_length=8,
        description="供模型读取的用途说明，必须写清触发条件与不适用场景（docs/04 §6 陷阱 2）",
    )
    category: str = Field(..., description="所属分组，如 risk / data / rule")
    input_schema: dict = Field(..., description="JSON Schema，强校验")
    output_schema: dict = Field(..., description="JSON Schema，强校验")
    deterministic: bool = Field(
        ...,
        description="决定能否缓存、能否作为证据、是否走模型档位（docs/04 §2.1）",
    )
    owner_agents: list[str] = Field(
        ..., min_length=1, description="允许调用的智能体白名单（铁律三）"
    )
    permission_scope: PermissionScope = PermissionScope.OPERATOR
    rate_limit: RateLimit = Field(default_factory=lambda: RateLimit(max_calls=120, window_s=60))
    timeout_ms: int = Field(default=10000, gt=0)
    impl_mode: ImplMode = ImplMode.RULE
    audit_level: AuditLevel = AuditLevel.SUMMARY
    version: str = Field(default="v1.0")
    cache_ttl_s: int = Field(
        default=0, ge=0, description="仅 deterministic=true 允许大于 0（docs/04 §6 陷阱 7）"
    )
    enabled: bool = True

    source_file: str | None = Field(default=None, exclude=True)

    @property
    def group(self) -> str:
        return self.skill_id.split(".", 1)[0]
