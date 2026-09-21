"""ModelRouter 骨架（M0）。

依据：docs/07 §1.4「ModelRouter 抽象」。

唯一约束：**业务代码不感知模型来源，只声明任务档位**。
本阶段只支持 `stub` provider（docs/11 §3.5 允许简化：模型调用返回 stub）。
禁止在业务代码里直连任何模型 API（docs/07 §1.5 第 6 条：密钥只走环境变量）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from contracts.enums import ModelBinding


@dataclass
class ProfileBinding:
    """一个档位在某个 profile 下的绑定（docs/07 §1.4 的 profiles 段）。"""

    profile: str
    binding: ModelBinding
    provider: str
    model: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StubResponse:
    """stub 推理返回。M0 不接真实模型，仅验证路由链路。"""

    text: str
    model: str
    profile: str
    binding: ModelBinding
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    degraded: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class StubProvider:
    """占位 provider：返回固定值，不含任何真实模型调用。"""

    name = "stub"

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        system: str | None = None,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # 返回固定结构，便于上层按 schema 校验（M1 起使用）
        return {
            "text": f"[stub:{model}] {prompt[:40]}",
            "prompt_tokens": len(prompt),
            "completion_tokens": 16,
            "latency_ms": 1,
        }

    def embed(self, *, model: str, texts: list[str], **kwargs: Any) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]

    def rerank(self, *, model: str, query: str, candidates: list[str], **kwargs: Any) -> list[float]:
        return [0.0] * len(candidates)


class ModelRouter:
    """统一模型路由（docs/07 §1.4）。

    - `resolve(agent=..., binding=...)` 返回档位绑定
    - 未配置档位时回落到 `default_profile`
    - 未知 provider 直接拒绝（不静默降级到真实调用）
    """

    def __init__(
        self,
        *,
        profiles: dict[str, dict[str, Any]] | None = None,
        routing_rules: list[dict[str, Any]] | None = None,
        default_profile: str = "hybrid",
        fallback_chain: list[str] | None = None,
        on_timeout_ms: int = 20000,
    ) -> None:
        self._profiles = profiles or {}
        self._routing_rules = routing_rules or []
        self._default_profile = default_profile
        self._fallback_chain = fallback_chain or []
        self.on_timeout_ms = on_timeout_ms
        self._providers: dict[str, Any] = {"stub": StubProvider()}

    # ------------------------------------------------------------------ 路由
    def resolve_profile(self, *, agent: str | None = None, phase: str | None = None) -> str:
        """按 routing_rules 匹配 profile（docs/07 §1.4）。"""
        for rule in self._routing_rules:
            match = rule.get("match", {})
            if match.get("agent") and match["agent"] != agent:
                continue
            if match.get("phase") and match["phase"] != phase:
                continue
            target = rule.get("profile")
            if target:
                return target
        return self._default_profile

    def resolve(
        self,
        *,
        binding: ModelBinding,
        agent: str | None = None,
        phase: str | None = None,
        profile: str | None = None,
    ) -> ProfileBinding:
        """解析出具体档位绑定。"""
        profile = profile or self.resolve_profile(agent=agent, phase=phase)
        section = self._profiles.get(profile)
        if section is None:
            raise KeyError(f"模型 profile 未配置：{profile}")
        entry = section.get(binding.value)
        if entry is None:
            raise KeyError(f"profile {profile} 缺少档位 {binding.value}")
        provider = entry.get("provider", "stub")
        if provider not in self._providers:
            raise KeyError(
                f"provider {provider} 未注册（M0 仅支持 stub，禁止直连模型 API）"
            )
        return ProfileBinding(
            profile=profile,
            binding=binding,
            provider=provider,
            model=entry.get("model", "stub-model"),
            extra={k: v for k, v in entry.items() if k not in {"provider", "model"}},
        )

    # ------------------------------------------------------------------ 调用
    def complete(
        self,
        *,
        binding: ModelBinding,
        prompt: str,
        agent: str | None = None,
        phase: str | None = None,
        profile: str | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> StubResponse:
        """统一补全入口。业务代码只声明档位，不感知 provider。"""
        resolved = self.resolve(binding=binding, agent=agent, phase=phase, profile=profile)
        provider = self._providers[resolved.provider]
        raw = provider.complete(
            model=resolved.model, prompt=prompt, system=system,
            max_tokens=kwargs.pop("max_tokens", None), **kwargs
        )
        return StubResponse(
            text=raw.get("text", ""),
            model=resolved.model,
            profile=resolved.profile,
            binding=resolved.binding,
            prompt_tokens=int(raw.get("prompt_tokens", 0)),
            completion_tokens=int(raw.get("completion_tokens", 0)),
            latency_ms=int(raw.get("latency_ms", 0)),
            raw=raw,
        )

    def embed(self, *, texts: list[str], profile: str | None = None) -> list[list[float]]:
        resolved = self.resolve(binding=ModelBinding.EMBED, profile=profile)
        return self._providers[resolved.provider].embed(model=resolved.model, texts=texts)

    # ------------------------------------------------------------------ 自检
    def describe(self) -> dict[str, Any]:
        bindings = sorted(
            {
                f"{p}.{b}"
                for p, section in self._profiles.items()
                for b in section
            }
        )
        return {
            "profiles": sorted(self._profiles),
            "bindings": bindings,
            "providers": sorted(self._providers),
            "default_profile": self._default_profile,
        }
