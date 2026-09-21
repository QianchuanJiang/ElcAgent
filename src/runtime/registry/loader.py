"""配置扫描与 schema 校验（M0）。

依据：docs/04 §5「注册与发现：启动时扫描注册表，校验 schema 合法性；
发现冲突则拒绝启动（快速失败）」、docs/09 §4.3（能力索引）。

扫描范围：
  config/agents/*.yaml           -> AgentCard
  config/skills_registry.yaml    -> SkillSpec[]
  config/capability_templates.yaml -> CapabilitySpec[] + CapabilityTemplate[]
  config/model_router.yaml       -> ModelRouter 配置

铁律三：注册表可扫描加载，不是硬编码字典。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from contracts import (
    AgentCard,
    CapabilitySpec,
    CapabilityTemplate,
    SkillSpec,
)

from .errors import (
    DuplicateDefinitionError,
    NotFoundError,
    SchemaValidationError,
)


def load_yaml(path: Path) -> Any:
    """读取 YAML；解析失败时指出文件与行列。"""
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as exc:  # pragma: no cover - 依赖具体输入
        raise SchemaValidationError(f"YAML 解析失败：{exc}", source_file=str(path)) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("配置文件不存在", source_file=str(path)) from exc


def _format_pydantic_error(exc: ValidationError) -> tuple[str, str | None]:
    """把 pydantic 校验错误转成「哪个字段、什么原因」。"""
    err = exc.errors()[0]
    loc = ".".join(str(p) for p in err.get("loc", ()))
    msg = err.get("msg", "校验失败")
    return f"{msg}（共 {len(exc.errors())} 处）", loc or None


def load_agents(config_dir: Path) -> list[AgentCard]:
    """扫描 config/agents/*.yaml。"""
    agents_dir = config_dir / "agents"
    if not agents_dir.is_dir():
        raise NotFoundError("agents 目录不存在", source_file=str(agents_dir))

    cards: list[AgentCard] = []
    seen: dict[str, str] = {}
    for path in sorted(agents_dir.glob("*.yaml")):
        raw = load_yaml(path) or {}
        if not isinstance(raw, dict):
            raise SchemaValidationError("文件根节点必须是 mapping", source_file=str(path))
        # 单文件单卡片；若为列表则逐张加载
        items = raw.get("agents") if "agents" in raw else [raw]
        if not isinstance(items, list):
            raise SchemaValidationError("agents 必须是列表", source_file=str(path), field="agents")
        for item in items:
            try:
                card = AgentCard.model_validate(item)
            except ValidationError as exc:
                detail, field = _format_pydantic_error(exc)
                raise SchemaValidationError(detail, source_file=str(path), field=field) from exc
            if card.agent_id in seen:
                raise DuplicateDefinitionError(
                    f"agent_id {card.agent_id} 重复定义（另见 {seen[card.agent_id]}）",
                    source_file=str(path),
                    field="agent_id",
                )
            seen[card.agent_id] = str(path)
            card.source_file = str(path)
            cards.append(card)
    return cards


def load_skills(config_dir: Path) -> list[SkillSpec]:
    """读取 config/skills_registry.yaml。"""
    path = config_dir / "skills_registry.yaml"
    raw = load_yaml(path) or {}
    if not isinstance(raw, dict) or "skills" not in raw:
        raise SchemaValidationError(
            "缺少顶层 `skills` 列表", source_file=str(path), field="skills"
        )
    skills_raw = raw["skills"]
    if not isinstance(skills_raw, list) or not skills_raw:
        raise SchemaValidationError("`skills` 必须是非空列表", source_file=str(path), field="skills")

    skills: list[SkillSpec] = []
    seen: set[str] = set()
    for idx, item in enumerate(skills_raw):
        try:
            spec = SkillSpec.model_validate(item)
        except ValidationError as exc:
            detail, field = _format_pydantic_error(exc)
            raise SchemaValidationError(
                f"skills[{idx}]：{detail}", source_file=str(path), field=field
            ) from exc
        if spec.skill_id in seen:
            raise DuplicateDefinitionError(
                f"skill_id {spec.skill_id} 重复定义", source_file=str(path), field="skill_id"
            )
        # 非确定性技能不允许配置缓存（docs/04 §6 陷阱 7）
        if not spec.deterministic and spec.cache_ttl_s > 0:
            raise SchemaValidationError(
                "非确定性技能不允许开启缓存（deterministic=false 时 cache_ttl_s 必须为 0）",
                source_file=str(path),
                field=f"skills[{idx}].cache_ttl_s",
            )
        seen.add(spec.skill_id)
        spec.source_file = str(path)
        skills.append(spec)
    return skills


def load_capabilities(
    config_dir: Path,
) -> tuple[list[CapabilitySpec], list[CapabilityTemplate]]:
    """读取 config/capability_templates.yaml。

    文件含两段：
      capabilities: [CapabilitySpec]        # docs/09 §5.1 的输入输出声明
      templates:    [CapabilityTemplate]    # docs/09 §4.2 的意图 → 能力需求
    """
    path = config_dir / "capability_templates.yaml"
    raw = load_yaml(path) or {}
    if not isinstance(raw, dict):
        raise SchemaValidationError("文件根节点必须是 mapping", source_file=str(path))

    caps_raw = raw.get("capabilities") or []
    if not caps_raw:
        raise SchemaValidationError(
            "缺少顶层 `capabilities` 列表", source_file=str(path), field="capabilities"
        )
    specs: list[CapabilitySpec] = []
    seen: set[str] = set()
    for idx, item in enumerate(caps_raw):
        try:
            spec = CapabilitySpec.model_validate(item)
        except ValidationError as exc:
            detail, field = _format_pydantic_error(exc)
            raise SchemaValidationError(
                f"capabilities[{idx}]：{detail}", source_file=str(path), field=field
            ) from exc
        if spec.capability in seen:
            raise DuplicateDefinitionError(
                f"capability {spec.capability} 重复定义",
                source_file=str(path),
                field="capability",
            )
        seen.add(spec.capability)
        specs.append(spec)

    tpl_raw = raw.get("templates") or []
    if not tpl_raw:
        raise SchemaValidationError(
            "缺少顶层 `templates` 列表", source_file=str(path), field="templates"
        )
    templates: list[CapabilityTemplate] = []
    seen_intents: set[str] = set()
    for idx, item in enumerate(tpl_raw):
        try:
            tpl = CapabilityTemplate.model_validate(item)
        except ValidationError as exc:
            detail, field = _format_pydantic_error(exc)
            raise SchemaValidationError(
                f"templates[{idx}]：{detail}", source_file=str(path), field=field
            ) from exc
        if tpl.intent.value in seen_intents:
            raise DuplicateDefinitionError(
                f"意图模板 {tpl.intent.value} 重复定义",
                source_file=str(path),
                field="intent",
            )
        seen_intents.add(tpl.intent.value)
        templates.append(tpl)
    return specs, templates


def load_model_router_config(config_dir: Path) -> dict[str, Any]:
    """读取 config/model_router.yaml（档位骨架）。"""
    path = config_dir / "model_router.yaml"
    raw = load_yaml(path) or {}
    if not isinstance(raw, dict) or "model_router" not in raw:
        raise SchemaValidationError(
            "缺少顶层 `model_router` 段", source_file=str(path), field="model_router"
        )
    return raw["model_router"]
