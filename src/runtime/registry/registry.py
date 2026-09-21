"""Agent Registry（M0）。

依据：docs/01 §3（Agent Card 统一加载）、docs/09 §4.3（能力 → 智能体反向索引）、
docs/04 §5（技能注册与发现）。

三条铁律中与注册表相关的两条在此落地：
  铁律三：技能可扫描加载、schema 强校验、越权调用被拒 —— 注册表不是硬编码字典
  铁律一：能力索引由 Agent Card 的 capabilities 自动构建，供后续「模板 → 图」查表

加载期一致性校验（不通过即拒绝启动）：
  ① Agent Card 引用的技能必须存在于注册表               -> docs/11 §3.4 验收项 4
  ② 能力模板引用的能力必须已在 capabilities 段声明       -> docs/11 §3.4 验收项 3
  ③ 能力模板引用的备选 agent 必须存在于 Agent Card 集合
  ④ id 不得重复
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from contracts import (
    AgentCapabilityIndex,
    AgentCard,
    CapabilityProvider,
    CapabilitySpec,
    CapabilityTemplate,
    Intent,
    SkillSpec,
)

from .errors import (
    NotFoundError,
    UnknownReferenceError,
)
from .loader import (
    load_agents,
    load_capabilities,
    load_model_router_config,
    load_skills,
)


@dataclass
class Registry:
    """注册表：智能体 / 技能 / 能力 / 模板 / 模型档位。"""

    agents: dict[str, AgentCard] = field(default_factory=dict)
    skills: dict[str, SkillSpec] = field(default_factory=dict)
    capabilities: dict[str, CapabilitySpec] = field(default_factory=dict)
    templates: dict[str, CapabilityTemplate] = field(default_factory=dict)
    #: 能力 → 智能体反向索引（docs/09 §4.3），由 Agent Card 自动构建
    capability_index: dict[str, AgentCapabilityIndex] = field(default_factory=dict)
    model_router_config: dict = field(default_factory=dict)
    config_dir: Path | None = None

    # ------------------------------------------------------------------ 查询
    def agent(self, agent_id: str) -> AgentCard:
        card = self.agents.get(agent_id)
        if card is None:
            raise NotFoundError(f"智能体 {agent_id} 未注册", field="agent_id")
        return card

    def skill(self, skill_id: str) -> SkillSpec:
        spec = self.skills.get(skill_id)
        if spec is None:
            raise NotFoundError(f"技能 {skill_id} 未注册", field="skill_id")
        return spec

    def capability(self, capability: str) -> CapabilitySpec:
        spec = self.capabilities.get(capability)
        if spec is None:
            raise NotFoundError(f"能力 {capability} 未定义", field="capability")
        return spec

    def template(self, intent: Intent | str) -> CapabilityTemplate:
        key = intent.value if isinstance(intent, Intent) else intent
        tpl = self.templates.get(key)
        if tpl is None:
            raise NotFoundError(f"意图 {key} 无能力需求模板", field="intent")
        return tpl

    def providers_of(self, capability: str) -> list[CapabilityProvider]:
        """能力的候选提供者，按 priority 升序（docs/09 §4.3）。"""
        index = self.capability_index.get(capability)
        return index.at_priority() if index else []

    # ------------------------------------------------------------------ 构建
    @classmethod
    def load(cls, config_dir: str | Path) -> "Registry":
        """扫描 config/ 并完成一致性校验；任一不通过即抛错（拒绝启动）。"""
        config_dir = Path(config_dir)
        if not config_dir.is_dir():
            raise NotFoundError("配置目录不存在", source_file=str(config_dir))

        agents = load_agents(config_dir)
        skills = load_skills(config_dir)
        cap_specs, templates = load_capabilities(config_dir)
        router_cfg = load_model_router_config(config_dir)

        registry = cls(
            agents={a.agent_id: a for a in agents},
            skills={s.skill_id: s for s in skills},
            capabilities={c.capability: c for c in cap_specs},
            templates={t.intent.value: t for t in templates},
            model_router_config=router_cfg,
            config_dir=config_dir,
        )
        registry._build_capability_index()
        registry._validate(cap_specs, templates)
        return registry

    def _build_capability_index(self) -> None:
        """由 Agent Card 的 capabilities 构建反向索引（单一配置源，无第二份）。"""
        index: dict[str, AgentCapabilityIndex] = {}
        for card in self.agents.values():
            for cap in card.capabilities:
                index.setdefault(cap, AgentCapabilityIndex(capability=cap))
                index[cap].providers.append(
                    CapabilityProvider(
                        agent=card.agent_id,
                        priority=1,
                        version=card.version,
                    )
                )
        self.capability_index = index

    def _validate(
        self,
        cap_specs: list[CapabilitySpec],
        templates: list[CapabilityTemplate],
    ) -> None:
        """启动期一致性校验（快速失败）。"""
        # ① Agent Card 的 skills 白名单必须指向已注册技能
        for card in self.agents.values():
            for skill_id in card.skills:
                if skill_id not in self.skills:
                    raise UnknownReferenceError(
                        f"Agent Card {card.agent_id} 引用了未注册的技能 {skill_id}",
                        source_file=card.source_file,
                        field=f"agents.{card.agent_id}.skills",
                    )

        # ② 技能 owner_agents 白名单必须指向已注册智能体（防止反向悬空）
        for spec in self.skills.values():
            for agent_id in spec.owner_agents:
                if agent_id not in self.agents:
                    raise UnknownReferenceError(
                        f"技能 {spec.skill_id} 的 owner_agents 引用了未注册智能体 {agent_id}",
                        source_file=spec.source_file,
                        field=f"skills.{spec.skill_id}.owner_agents",
                    )

        # ③ 模板引用的能力必须已在 capabilities 段声明（docs/11 §3.4 验收项 3）
        for tpl in templates:
            for req in tpl.requires:
                if req.capability not in self.capabilities:
                    raise UnknownReferenceError(
                        f"能力模板 {tpl.intent.value} 引用了不存在的能力 {req.capability}",
                        source_file=str((self.config_dir or Path(".")) / "capability_templates.yaml"),
                        field=f"templates.{tpl.intent.value}.requires.capability",
                    )

        # ④ required 能力必须有可用提供者（否则启动即暴露配置缺口，符合快速失败）
        for tpl in templates:
            for req in tpl.requires:
                if req.mode.value == "required" and not self.providers_of(req.capability):
                    raise UnknownReferenceError(
                        f"能力模板 {tpl.intent.value} 的必需能力 {req.capability} 无任何智能体提供",
                        source_file=str((self.config_dir or Path(".")) / "capability_templates.yaml"),
                        field=f"templates.{tpl.intent.value}.requires.{req.capability}",
                    )

        # ⑤ 能力规格若无人提供（仅提示性，不拒绝启动；输出在自检中）
        #    不做 raise：M0 只注册 2 个智能体，能力可有缺口但必须是 required 之外的。

    # ------------------------------------------------------------------ 汇报
    def summary(self) -> dict[str, int]:
        """自检输出用（docs/11 §3.4 验收项 1）。"""
        return {
            "agents": len(self.agents),
            "skills": len(self.skills),
            "capabilities": len(self.capabilities),
            "templates": len(self.templates),
        }

    def report_line(self) -> str:
        s = self.summary()
        return (
            f"已注册 {s['agents']} 个智能体 / {s['skills']} 个技能 / "
            f"{s['templates']} 个能力模板（能力定义 {s['capabilities']} 个）"
        )

    def unprovided_capabilities(self) -> list[str]:
        """列出没有任何智能体提供的能力（M0 自检提示项）。"""
        return sorted(c for c in self.capabilities if not self.providers_of(c))

    def dangling_skills(self) -> list[str]:
        """列出无任何调用者的技能（M0 自检提示项）。"""
        declared: set[str] = set()
        for card in self.agents.values():
            declared.update(card.skills)
        return sorted(s for s in self.skills if s not in declared)
