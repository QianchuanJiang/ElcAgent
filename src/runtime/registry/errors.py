"""注册表加载期错误。

设计依据：docs/04 §5「发现冲突则拒绝启动（快速失败）」。
错误信息必须**指出是哪个文件、哪个字段**（docs/11 §3.4 验收项 2/3/4）。
"""

from __future__ import annotations


class RegistryError(Exception):
    """注册表加载失败基类。"""

    def __init__(self, message: str, *, source_file: str | None = None, field: str | None = None):
        self.source_file = source_file
        self.field = field
        parts = []
        if source_file:
            parts.append(f"文件={source_file}")
        if field:
            parts.append(f"字段={field}")
        prefix = f"[{', '.join(parts)}] " if parts else ""
        super().__init__(f"{prefix}{message}")


class SchemaValidationError(RegistryError):
    """Pydantic schema 校验失败（缺必填字段、类型非法等）。"""


class DuplicateDefinitionError(RegistryError):
    """定义冲突：同一 id 被定义两次。"""


class UnknownReferenceError(RegistryError):
    """引用不存在的对象（技能 / 能力 / 智能体）。"""


class NotFoundError(RegistryError):
    """查询目标不存在。"""
