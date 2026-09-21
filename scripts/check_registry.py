#!/usr/bin/env python
"""启动自检：加载注册表并输出汇报（docs/11 §3.2、§3.4 验收项 1）。

用法：
    python scripts/check_registry.py [--config config] [--strict]

退出码：
    0  加载通过
    1  加载失败（schema 非法 / 引用悬空 / 定义冲突），错误信息指出文件与字段
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# src layout：把 src/ 加入 import path
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from memory.store.schema import TABLES, create_all, create_engine_for  # noqa: E402
from model.router import ModelRouter  # noqa: E402
from runtime.registry import Registry, RegistryError  # noqa: E402


def build_router(registry: Registry) -> ModelRouter:
    """按配置构建 ModelRouter（M0 只注册 stub provider）。"""
    cfg = registry.model_router_config
    fallback = cfg.get("fallback", {}) or {}
    return ModelRouter(
        profiles=cfg.get("profiles", {}) or {},
        routing_rules=cfg.get("routing_rules", []) or [],
        default_profile=cfg.get("default_profile", "stub"),
        fallback_chain=fallback.get("chain", []) or [],
        on_timeout_ms=int(fallback.get("on_timeout_ms", 20000)),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ElecAgent M0 启动自检")
    parser.add_argument("--config", default=str(ROOT / "config"), help="配置目录")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="严格模式：能力/技能存在缺口时也返回非零退出码",
    )
    args = parser.parse_args(argv)

    print("ElecAgent M0 · 契约与骨架自检")
    print("-" * 62)

    # ① 注册表加载（冲突则拒绝启动）
    try:
        registry = Registry.load(args.config)
    except RegistryError as exc:
        print(f"[FAIL] 注册表加载被拒绝\n       {exc}")
        return 1

    print(f"[OK] {registry.report_line()}")
    for card in sorted(registry.agents.values(), key=lambda c: c.agent_id):
        print(
            f"     · 智能体 {card.agent_id:<20} 技能白名单={len(card.skills)} "
            f"能力={len(card.capabilities)} 档位={card.model_binding.value}"
        )
    for spec in sorted(registry.skills.values(), key=lambda s: s.skill_id):
        print(
            f"     · 技能   {spec.skill_id:<28} 模式={spec.impl_mode.value:<8} "
            f"确定性={str(spec.deterministic):<5} 白名单={','.join(spec.owner_agents)}"
        )
    for key, tpl in sorted(registry.templates.items()):
        modes: dict[str, int] = {}
        for req in tpl.requires:
            modes[req.mode.value] = modes.get(req.mode.value, 0) + 1
        mode_str = " ".join(f"{k}={v}" for k, v in sorted(modes.items()))
        print(f"     · 模板   {key:<28} {mode_str} 终态={tpl.terminal_output}")

    # ② ModelRouter
    router = build_router(registry)
    info = router.describe()
    print(
        f"[OK] ModelRouter profiles={info['profiles']} providers={info['providers']} "
        f"default={info['default_profile']}"
    )

    # ③ 最小表集建表
    engine = create_engine_for("sqlite:///:memory:")
    names = create_all(engine)
    if set(names) != {t.name for t in TABLES}:
        print("[FAIL] 建表结果与最小表集不一致")
        return 1
    print(f"[OK] 最小表集 {len(names)} 张：{', '.join(names)}")

    # ④ 缺口提示（不视为失败，除非 --strict）
    gaps: list[str] = []
    unprovided = registry.unprovided_capabilities()
    if unprovided:
        gaps.append(f"无智能体提供的能力：{', '.join(unprovided)}")
    dangling = registry.dangling_skills()
    if dangling:
        gaps.append(f"无调用者的技能：{', '.join(dangling)}")
    if gaps:
        label = "[FAIL]" if args.strict else "[WARN]"
        for g in gaps:
            print(f"{label} {g}")

    print("-" * 62)
    print(registry.report_line())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
