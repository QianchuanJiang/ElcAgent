"""Agent Registry：扫描 config/、校验 schema、加载注册表；冲突则拒绝启动。"""

from .errors import (
    DuplicateDefinitionError,
    NotFoundError,
    RegistryError,
    SchemaValidationError,
    UnknownReferenceError,
)
from .loader import (
    load_agents,
    load_capabilities,
    load_model_router_config,
    load_skills,
    load_yaml,
)
from .registry import Registry

__all__ = [
    "Registry",
    "RegistryError",
    "SchemaValidationError",
    "DuplicateDefinitionError",
    "UnknownReferenceError",
    "NotFoundError",
    "load_yaml",
    "load_agents",
    "load_skills",
    "load_capabilities",
    "load_model_router_config",
]
