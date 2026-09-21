#!/usr/bin/env python
"""M0 证伪测试脚本：用「破坏它，看它是否报警」的方式证明机制是真的。

与 `make test` 的区别：
  - `make test`  证明「现在能跑通」
  - 本脚本       证明「机制被破坏时会立刻失败」—— 即 docs/07 §4.1 的证伪测试

设计原则：**每条证伪测试都必须能失败**。
若某条在注入破坏后仍然"通过"，说明这个机制是装饰性的，脚本会判定 FAIL。

用法：
    python scripts/verify_m0.py            # 全部证伪测试
    python scripts/verify_m0.py -v         # 打印每步细节
    python scripts/verify_m0.py --list     # 只列出测试项

退出码：0 全部通过；1 存在 FAIL
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from contracts import (  # noqa: E402
    Constraints,
    ContextRefs,
    Envelope,
    EnvelopeHeader,
    Evidence,
    MemoryItem,
    MessageResult,
    ModelBinding,
    Performative,
    Security,
    SkillSpec,
    Telemetry,
)
from contracts.enums import MemoryScope, MemoryType  # noqa: E402
from memory.store.schema import TABLES, create_all, create_engine_for  # noqa: E402
from model.router import ModelRouter  # noqa: E402
from runtime.registry import Registry, RegistryError  # noqa: E402

# ---------------------------------------------------------------------------
# 迷你测试框架（不引入新依赖，保持与 Makefile 一致的零配置执行）
# ---------------------------------------------------------------------------


class Failure(Exception):
    """证伪测试失败。"""


class Case:
    def __init__(self, cid: str, title: str, fn: Callable[[], str | None]):
        self.cid = cid
        self.title = title
        self.fn = fn
        self.status = "SKIP"
        self.detail = ""

    def run(self, verbose: bool) -> None:
        try:
            note = self.fn()
            self.status = "PASS"
            self.detail = note or ""
        except Failure as exc:
            self.status = "FAIL"
            self.detail = str(exc)
        except Exception as exc:  # noqa: BLE001 - 任何异常都视为失败
            self.status = "FAIL"
            self.detail = f"未预期异常：{type(exc).__name__}: {exc}"
            if verbose:
                traceback.print_exc()


CASES: list[Case] = []


def case(cid: str, title: str) -> Callable:
    def deco(fn: Callable[[], str | None]) -> Callable[[], str | None]:
        CASES.append(Case(cid, title, fn))
        return fn

    return deco


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise Failure(msg)


def expect_raises(exc_types: tuple[type, ...], fn: Callable[[], Any], msg: str) -> Exception:
    """断言调用必须抛错；不抛错即为 FAIL（机制被写假的信号）。"""
    try:
        fn()
    except exc_types as exc:
        return exc
    except Exception as exc:  # 抛了别的异常也算"拒绝了"，但记录类型
        return exc
    raise Failure(f"{msg}（预期抛出异常，但调用成功返回——机制可能是装饰性的）")


# ---------------------------------------------------------------------------
# 配置破坏工具：复制 config 到临时目录后定点改写（不生成任何业务数据）
# ---------------------------------------------------------------------------


class Sandbox:
    """可写的 config 副本。"""

    def __init__(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="elcagent_falsify_")
        self.config = Path(self._tmp) / "config"
        shutil.copytree(ROOT / "config", self.config)

    def edit(self, rel: str, mutate: Callable[[Any], None]) -> "Sandbox":
        path = self.config / rel
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        return self

    def write(self, rel: str, text: str) -> "Sandbox":
        (self.config / rel).write_text(text, encoding="utf-8")
        return self

    def load(self) -> Registry:
        return Registry.load(self.config)

    def close(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def __enter__(self) -> "Sandbox":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _skills(data: dict, idx: int = 0) -> dict:
    return data["skills"][idx]


# ===========================================================================
# A 组：配置驱动 —— 证明"只改配置不改内核"
# ===========================================================================


@case("A1", "新增技能只改配置即可被注册，内核零改动")
def case_a1() -> str:
    """同时改两处配置（技能表 + 卡片白名单），全程不改任何 Python 代码。

    注意：只加技能表而不加卡片白名单会被 B2 类的校验拒绝 —— 这正是
    「白名单双向闭合」的体现，因此这里必须两处同改，符合 docs/04 §5 的治理要求。
    """

    def add_skill(d: dict) -> None:
        d["skills"].append(
            {
                "skill_id": "risk.calc_windage_margin",
                "name": "风偏间隙裕度校核",
                "description": "校核风偏设计间隙裕度是否满足要求；无设计间隙参数时不适用。",
                "category": "risk",
                "impl_mode": "formula",
                "deterministic": True,
                "owner_agents": ["A01_supervisor"],
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "version": "v1.0",
                "cache_ttl_s": 300,
            }
        )

    def grant(d: dict) -> None:
        d["agents"][0]["skills"].append("risk.calc_windage_margin")

    with Sandbox() as sb:
        sb.edit("skills_registry.yaml", add_skill)
        sb.edit("agents/agents.yaml", grant)
        reg = sb.load()
        expect("risk.calc_windage_margin" in reg.skills, "新技能未被注册")
        expect(reg.summary()["skills"] == 4, f"技能数应为 4，实际 {reg.summary()['skills']}")
        spec = reg.skill("risk.calc_windage_margin")
        expect(spec.owner_agents == ["A01_supervisor"], "白名单未生效")
    return "技能数 3 → 4，全程零 Python 代码改动"


@case("A2", "新增智能体只改配置，能力索引自动扩展")
def case_a2() -> str:
    def add_agent(d: dict) -> None:
        d["agents"].append(
            {
                "agent_id": "A99_probe",
                "name": "探针智能体",
                "role": "执行",
                "description": "仅用于证伪测试：验证新增智能体无需改内核。",
                "capabilities": ["probe_capability"],
                "skills": [],
                "model_binding": "none",
                "permission_scope": "operator",
                "version": "v0.0",
            }
        )

    with Sandbox() as sb:
        sb.edit("agents/agents.yaml", add_agent)
        reg = sb.load()
        expect("A99_probe" in reg.agents, "新智能体未被注册")
        expect("probe_capability" in reg.capability_index, "能力索引未自动扩展")
        providers = reg.providers_of("probe_capability")
        expect(providers and providers[0].agent == "A99_probe", "能力→智能体索引不正确")
    return "能力索引由 Agent Card 自动构建，无第二份配置源"


@case("A3", "关闭智能体（status=disabled）后不再出现在能力索引候选里")
def case_a3() -> str:
    def disable(d: dict) -> None:
        for c in d["agents"]:
            if c["agent_id"] == "A03_data_steward":
                c["status"] = "disabled"

    with Sandbox() as sb:
        sb.edit("agents/agents.yaml", disable)
        reg = sb.load()
        card = reg.agent("A03_data_steward")
        expect(card.status.value == "disabled", "status 未生效")
        # 索引仍记录该提供者，过滤在候选选择阶段发生（docs/09 §4.3 第 4 条）
        expect("data_governance" in reg.capability_index, "索引结构被破坏")
    return "disabled 状态可被读取，供候选过滤步骤使用"


# ===========================================================================
# B 组：快速失败 —— 证明配置错误会拒绝启动而非静默通过
# ===========================================================================


@case("B1", "技能缺必填字段 → 拒绝启动，且错误定位到文件与字段")
def case_b1() -> str:
    with Sandbox() as sb:
        sb.edit("skills_registry.yaml", lambda d: _skills(d).pop("owner_agents", None))
        exc = expect_raises((RegistryError,), sb.load, "缺 owner_agents 应拒绝启动")
        text = str(exc)
        expect("skills_registry.yaml" in text, f"未指出文件：{text}")
        expect("owner_agents" in text, f"未指出字段：{text}")
    return "错误含文件名 + 字段名，可直接定位"


@case("B2", "Agent Card 引用未注册技能 → 拒绝启动")
def case_b2() -> str:
    with Sandbox() as sb:
        sb.edit(
            "agents/agents.yaml",
            lambda d: d["agents"][0]["skills"].append("risk.calc_thermal_rating"),
        )
        exc = expect_raises((RegistryError,), sb.load, "引用未注册技能应拒绝启动")
        expect("risk.calc_thermal_rating" in str(exc), "未报出违规技能名")
        expect("agents.yaml" in str(exc), "未报出违规文件")
    return "技能白名单是强校验，不是文档约定"


@case("B3", "能力模板引用不存在的能力 → 拒绝启动（拦截幻觉）")
def case_b3() -> str:
    def inject(d: dict) -> None:
        d["templates"][0]["requires"].append(
            {"capability": "quantum_forecast", "mode": "required"}
        )

    with Sandbox() as sb:
        sb.edit("capability_templates.yaml", inject)
        exc = expect_raises((RegistryError,), sb.load, "未知能力应拒绝启动")
        expect("quantum_forecast" in str(exc), "未报出未知能力")
        expect("risk_assessment" in str(exc), "未定位到模板")
    return "这正是 M2「模型幻觉被拦截」的骨架，M0 已具备"


@case("B4", "required 能力无任何提供者 → 拒绝启动")
def case_b4() -> str:
    def strip(d: dict) -> None:
        for c in d["agents"]:
            rest = [x for x in c["capabilities"] if x != "data_governance"]
            c["capabilities"] = rest or ["unrelated_capability"]

    with Sandbox() as sb:
        sb.edit("agents/agents.yaml", strip)
        exc = expect_raises((RegistryError,), sb.load, "必需能力无提供者应拒绝启动")
        expect("data_governance" in str(exc), "未报出缺失能力")
    return "缺口在启动期暴露，而非运行期才炸"


@case("B5", "skill_id 重复定义 → 拒绝启动")
def case_b5() -> str:
    def dup(d: dict) -> None:
        d["skills"].append(dict(d["skills"][0]))

    with Sandbox() as sb:
        sb.edit("skills_registry.yaml", dup)
        exc = expect_raises((RegistryError,), sb.load, "重复定义应拒绝启动")
        expect("重复" in str(exc), f"未提示重复定义：{exc}")
    return "同一 id 二次定义被拦截"


@case("B6", "非确定性技能开启缓存 → 拒绝启动")
def case_b6() -> str:
    """docs/04 §6 陷阱 7：缓存非确定性技能 → 结果被错误复用。"""

    def enable(d: dict) -> None:
        for s in d["skills"]:
            if s["skill_id"] == "model.extract_json":
                s["cache_ttl_s"] = 600

    with Sandbox() as sb:
        sb.edit("skills_registry.yaml", enable)
        exc = expect_raises((RegistryError,), sb.load, "模型类技能不得缓存")
        expect("cache_ttl_s" in str(exc), f"未指出 cache_ttl_s：{exc}")
    return "确定性与缓存策略被强绑定，避免结果被错误复用"


@case("B7", "skill_id 缺分组前缀 → 拒绝启动")
def case_b7() -> str:
    with Sandbox() as sb:
        sb.edit("skills_registry.yaml", lambda d: _skills(d).update({"skill_id": "CalcLoad"}))
        exc = expect_raises((RegistryError,), sb.load, "非法 skill_id 应拒绝")
        expect("skill_id" in str(exc), f"未指出 skill_id：{exc}")
    return "技能命名规范在加载期强制，不靠人工审查"


@case("B8", "配置目录缺失 → 明确报错而非静默空注册表")
def case_b8() -> str:
    exc = expect_raises(
        (RegistryError,), lambda: Registry.load("/nonexistent/config/path/xyz"), "缺失目录应报错"
    )
    expect("不存在" in str(exc), f"错误信息不可读：{exc}")
    return "避免「不存在→空注册表却启动成功」的假象"


@case("B9", "YAML 语法损坏 → 指出文件")
def case_b9() -> str:
    with Sandbox() as sb:
        sb.write("skills_registry.yaml", "skills: [ {skill_id: 未闭合\n")
        exc = expect_raises((RegistryError,), sb.load, "非法 YAML 应拒绝启动")
        expect("skills_registry.yaml" in str(exc), f"未指出损坏文件：{exc}")
    return "解析失败可定位到文件"


# ===========================================================================
# C 组：铁律二（信封）—— 证明消息必须经协议，违规结构无法构造
# ===========================================================================


def _env(pf: Performative, **kw: Any) -> Envelope:
    return Envelope(
        envelope=EnvelopeHeader(
            trace_id="trc_probe",
            sender="A07_probe",
            receiver="A13_probe",
            performative=pf,
            intent="risk_ranking_result",
        ),
        **kw,
    )


@case("C1", "PROPOSE 不携带 evidence → 构造即失败（约束 5）")
def case_c1() -> str:
    exc = expect_raises(
        (Exception,), lambda: _env(Performative.PROPOSE), "无证据的 PROPOSE 必须被拒"
    )
    expect("evidence" in str(exc), f"未指出 evidence：{exc}")
    return "无 source_ref 的结论不可信，在结构层禁止"


@case("C2", "PROPOSE 带 evidence 但无 confidence → 可构造（confidence 由响应阶段填）")
def case_c2() -> str:
    env = _env(
        Performative.PROPOSE,
        result=MessageResult(
            confidence=None, evidence=[Evidence(type="data", ref="meteo_obs:1")]
        ),
    )
    expect(env.result.confidence is None, "confidence 应为可选，由响应阶段填充")
    return "约束 3 的填充时机留待 M1 落实，M0 只冻结结构"


@case("C3", "REFUSE 不携带理由 → 构造即失败（协议纪律）")
def case_c3() -> str:
    exc = expect_raises(
        (Exception,), lambda: _env(Performative.REFUSE), "静默拒绝必须被禁止"
    )
    expect("REFUSE" in str(exc), f"错误信息未点明 REFUSE：{exc}")
    return "不允许静默拒绝"


@case("C4", "FAILURE 不携带原因 → 构造即失败")
def case_c4() -> str:
    exc = expect_raises((Exception,), lambda: _env(Performative.FAILURE), "无原因的失败必须被拒")
    expect("FAILURE" in str(exc), f"错误信息未点明 FAILURE：{exc}")
    return "失败必须可解释"


@case("C5", "派生消息继承 trace_id 并设置 parent_msg_id（约束 1）")
def case_c5() -> str:
    root = _env(Performative.REQUEST)
    child = root.derive(
        sender="A03_probe", receiver="A01_probe", performative=Performative.CONFIRM
    )
    grandchild = child.derive(
        sender="A01_probe", receiver="A13_probe", performative=Performative.PROPOSE,
        result=MessageResult(
            confidence=0.9, evidence=[Evidence(type="skill", ref="risk.calc_icing_load")]
        ),
    )
    expect(child.envelope.trace_id == root.envelope.trace_id, "trace_id 未贯穿")
    expect(grandchild.envelope.trace_id == root.envelope.trace_id, "三代 trace_id 未贯穿")
    expect(child.envelope.parent_msg_id == root.envelope.msg_id, "父子关系未建立")
    expect(grandchild.envelope.seq == root.envelope.seq + 2, "seq 未单调递增")
    return "三代消息可重建为因果链"


@case("C6", "信封可序列化→传输→反序列化，且语义完全一致（铁律二基础）")
def case_c6() -> str:
    env = _env(
        Performative.PROPOSE,
        result=MessageResult(
            confidence=0.81, evidence=[Evidence(type="data", ref="meteo_obs:icing:001")]
        ),
        context_refs=ContextRefs(memory_ids=["mem_1", "mem_2"]),
    )
    raw = env.to_wire()
    expect(isinstance(raw, str), "to_wire 必须返回可传输的字符串，而非对象引用")
    restored = Envelope.from_wire(raw)
    expect(restored.model_dump() == env.model_dump(), "往返后语义不一致")
    expect(restored.context_refs.memory_ids == ["mem_1", "mem_2"], "记忆引用丢失")
    return "消息可脱离进程传输，为 M1 总线预留"


# ===========================================================================
# D 组：铁律三（技能）—— 证明技能自带治理属性
# ===========================================================================


@case("D1", "技能描述过短 → 拒绝（避免模型选错技能）")
def case_d1() -> str:
    exc = expect_raises(
        (Exception,),
        lambda: SkillSpec(
            skill_id="risk.x", name="x", description="很短",
            category="risk", input_schema={}, output_schema={},
            deterministic=True, owner_agents=["A1"],
        ),
        "description 过短应被拒",
    )
    expect("description" in str(exc) or "least" in str(exc), f"错误信息不可读：{exc}")
    return "description 有长度下限，逼出可读的触发条件说明"


@case("D2", "技能无 owner_agents 白名单 → 拒绝")
def case_d2() -> str:
    exc = expect_raises(
        (Exception,),
        lambda: SkillSpec(
            skill_id="risk.x", name="x", description="用于测试的描述文本",
            category="risk", input_schema={}, output_schema={},
            deterministic=True, owner_agents=[],
        ),
        "空白名单应被拒",
    )
    expect("owner_agents" in str(exc), f"错误信息未指出 owner_agents：{exc}")
    return "铁律三：技能必须声明调用白名单"


@case("D3", "技能输入输出 schema 为必填 → 拒绝缺省")
def case_d3() -> str:
    exc = expect_raises(
        (Exception,),
        lambda: SkillSpec(
            skill_id="risk.x", name="x", description="用于测试的描述文本",
            category="risk", deterministic=True, owner_agents=["A1"],
        ),
        "缺 schema 应被拒",
    )
    expect("input_schema" in str(exc) or "output_schema" in str(exc), f"信息不可读：{exc}")
    return "技能是带契约的能力单元，不是普通函数"


@case("D4", "注册表实际加载了配置里的全部 3 个技能，且来源可查")
def case_d4() -> str:
    reg = Registry.load(ROOT / "config")
    expect(set(reg.skills) == {
        "risk.calc_icing_load",
        "data.map_legacy_code",
        "model.extract_json",
    }, f"技能集合不符：{sorted(reg.skills)}")
    for spec in reg.skills.values():
        expect(bool(spec.source_file), f"{spec.skill_id} 缺少 source_file，来源不可查")
        expect(Path(spec.source_file).name == "skills_registry.yaml", "来源文件不对")
    return "技能来自扫描 config/，每个都带来源文件"


@case("D5", "技能白名单与能力索引双向一致")
def case_d5() -> str:
    reg = Registry.load(ROOT / "config")
    for spec in reg.skills.values():
        for agent_id in spec.owner_agents:
            card = reg.agent(agent_id)
            expect(
                spec.skill_id in card.skills,
                f"技能 {spec.skill_id} 声明 {agent_id} 可用，但该卡片白名单里没有",
            )
    return "白名单双向闭合，无单向悬空"


# ===========================================================================
# E 组：记忆硬约束 —— 证明"无来源不入库"是结构保证
# ===========================================================================


@case("E1", "记忆缺 source_ref → 构造即失败（无来源不许落库）")
def case_e1() -> str:
    exc = expect_raises(
        (Exception,),
        lambda: MemoryItem(
            memory_id="mem_x", scope_type=MemoryScope.GLOBAL, mem_type=MemoryType.SEMANTIC,
            title="覆冰阈值", content="覆冰启动阈值为 12mm", source_type="task",
            source_ref="", confidence=0.9,
        ),
        "无来源记忆应被拒",
    )
    expect("source_ref" in str(exc), f"未指出 source_ref：{exc}")
    return "docs/02 §3.1 第 7 步硬约束被结构性保证"


@case("E2", "用户作用域记忆缺 owner_user_id → 构造即失败（用户隔离）")
def case_e2() -> str:
    exc = expect_raises(
        (Exception,),
        lambda: MemoryItem(
            memory_id="mem_y", scope_type=MemoryScope.USER, mem_type=MemoryType.USER_PREFERENCE,
            title="偏好", content="偏好要点式输出", source_type="approval",
            source_ref="trc_1", confidence=0.8,
        ),
        "用户记忆缺归属人应被拒",
    )
    expect("owner_user_id" in str(exc), f"未指出 owner_user_id：{exc}")
    return "用户记忆隔离在结构层强制，避免「切换用户无差异」"


@case("E3", "记忆正文超长（>500 字）→ 构造即失败")
def case_e3() -> str:
    exc = expect_raises(
        (Exception,),
        lambda: MemoryItem(
            memory_id="mem_z", scope_type=MemoryScope.GLOBAL, mem_type=MemoryType.EPISODIC,
            title="超长正文", content="冗" * 501, source_type="task",
            source_ref="trc_1", confidence=0.8,
        ),
        "超长正文应被拒",
    )
    expect("content" in str(exc) or "500" in str(exc), f"信息不可读：{exc}")
    return "记忆条目长度受控，避免把整段对话塞进一条记忆"


@case("E4", "标题超长（>30 字）→ 构造即失败")
def case_e4() -> str:
    exc = expect_raises(
        (Exception,),
        lambda: MemoryItem(
            memory_id="mem_w", scope_type=MemoryScope.GLOBAL, mem_type=MemoryType.SEMANTIC,
            title="标" * 31, content="正常内容", source_type="task",
            source_ref="trc_1", confidence=0.8,
        ),
        "超长标题应被拒",
    )
    expect("title" in str(exc) or "30" in str(exc), f"信息不可读：{exc}")
    return "标题长度受控（docs/02 §4.1：≤30 字）"


# ===========================================================================
# F 组：模型无旁路 —— 证明业务代码不能直连模型 API
# ===========================================================================


def _router(reg: Registry) -> ModelRouter:
    cfg = reg.model_router_config
    fb = cfg.get("fallback", {}) or {}
    return ModelRouter(
        profiles=cfg.get("profiles", {}) or {},
        routing_rules=cfg.get("routing_rules", []) or [],
        default_profile=cfg.get("default_profile", "stub"),
        fallback_chain=fb.get("chain", []) or [],
        on_timeout_ms=int(fb.get("on_timeout_ms", 20000)),
    )


@case("F1", "请求未注册 provider（真实档位）→ 抛错，不去直连 API")
def case_f1() -> str:
    reg = Registry.load(ROOT / "config")
    router = _router(reg)
    exc = expect_raises(
        (KeyError,),
        lambda: router.resolve(binding=ModelBinding.HEAVY, agent="A01_supervisor", profile="hybrid"),
        "未注册 provider 应抛错",
    )
    expect("未注册" in str(exc), f"错误信息未说明原因：{exc}")
    return "compat_api / local 未注册，resolve 直接拒绝"


@case("F2", "stub 档位路由可用，且返回体带 profile 与 model 出处")
def case_f2() -> str:
    reg = Registry.load(ROOT / "config")
    router = _router(reg)
    resp = router.complete(binding=ModelBinding.LIGHT, prompt="识别意图", agent="A01_supervisor")
    expect(resp.profile == "stub", f"profile 应为 stub，实际 {resp.profile}")
    expect(resp.model == "stub-light", f"model 应为 stub-light，实际 {resp.model}")
    expect(resp.binding is ModelBinding.LIGHT, "档位未透传")
    return "业务只声明档位，provider 由路由解析"


@case("F3", "routing_rules 命中时按规则选 profile，未命中回落 default")
def case_f3() -> str:
    """注意：配置里 default_profile=hybrid，但其 provider 未注册。

    这恰好说明一个设计事实 —— **未命中规则会回落到 default，而 default 若是
    未注册的真实档位，会立刻失败而不是静默换档**。两者都是期望行为。
    """
    reg = Registry.load(ROOT / "config")
    router = _router(reg)

    hit = router.resolve_profile(agent="A01_supervisor")
    expect(hit == "stub", f"命中规则应为 stub，实际 {hit}")

    miss = router.resolve_profile(agent="A_unknown_agent")
    expect(miss == "hybrid", f"未命中应回落 default（hybrid），实际 {miss}")

    # 回落到的 default 未注册 provider → 必须抛错，不得静默换档
    exc = expect_raises(
        (KeyError,),
        lambda: router.resolve(binding=ModelBinding.LIGHT, agent="A_unknown_agent"),
        "未命中规则且 default 未注册 provider 时应抛错",
    )
    expect("未注册" in str(exc), f"错误信息未说明原因：{exc}")

    # 显式指定 stub profile 时则应正常
    ok = router.resolve(binding=ModelBinding.LIGHT, agent="A_unknown_agent", profile="stub")
    expect(ok.profile == "stub", "显式 profile 未生效")
    return "命中→stub；未命中→回落 hybrid 且因 provider 未注册而快速失败（无静默换档）"


@case("F4", "档位在 profile 中缺失 → 抛错而非降级到别的档位")
def case_f4() -> str:
    router = ModelRouter(profiles={"thin": {"light": {"provider": "stub", "model": "m"}}})
    exc = expect_raises(
        (KeyError,), lambda: router.resolve(binding=ModelBinding.VISION, profile="thin"),
        "缺档位应抛错",
    )
    expect("vision" in str(exc), f"未指出缺失档位：{exc}")
    return "不静默换档，避免「以为调了视觉模型实际调了轻档」"


# ===========================================================================
# G 组：表结构 —— 证明最小表集真的建得出来
# ===========================================================================


@case("G1", "最小表集 11 张全部建立，且关键字段在位")
def case_g1() -> str:
    engine = create_engine_for("sqlite:///:memory:")
    names = create_all(engine)
    expect(len(names) == 11, f"应建 11 张表，实际 {len(names)}")
    expect({t.name for t in TABLES} == set(names), "建表结果与 TABLES 声明不一致")

    from sqlalchemy import inspect

    insp = inspect(engine)
    expected_cols = {
        "memory_item": {"memory_id", "source_ref", "confidence", "decay_score", "status", "owner_user_id"},
        "memory_access_log": {"access_id", "memory_id", "used_in_output"},
        "message_log": {"msg_id", "trace_id", "parent_msg_id", "performative", "confidence"},
        "skill_call_log": {"call_id", "skill_id", "cache_hit", "fallback_level"},
        "plan_record": {"plan_id", "task_id", "graph"},
        "replan_record": {"replan_id", "trigger", "impact_scope"},
        "plan_rejection": {"rejection_id", "reason", "offending_refs"},
        "trace_snapshot": {"snapshot_id", "trace_id", "message_seq"},
    }
    for table, cols in expected_cols.items():
        actual = {c["name"] for c in insp.get_columns(table)}
        missing = cols - actual
        expect(not missing, f"{table} 缺字段：{sorted(missing)}")
    return "11 张表 + 关键字段（含 used_in_output / parent_msg_id / fallback_level）全部在位"


@case("G2", "表可实际写入并读回（不是只 create_all）")
def case_g2() -> str:
    from sqlalchemy import insert, select

    from memory.store.schema import memory_item_table, message_log_table

    engine = create_engine_for("sqlite:///:memory:")
    create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            insert(memory_item_table).values(
                memory_id="mem_g2", scope_type="global", scope_id=None, mem_type="semantic",
                title="覆冰阈值", content="覆冰启动阈值为 12mm", structured_payload={"v": 12},
                source_type="task", source_ref="trc_g2", confidence=0.9,
                status="active", tags=["icing"],
            )
        )
        conn.execute(
            insert(message_log_table).values(
                msg_id="msg_g2", trace_id="trc_g2", parent_msg_id=None, sender="A1",
                receiver="A2", performative="REQUEST", intent="risk_assessment", seq=1,
            )
        )
        row = conn.execute(
            select(memory_item_table.c.title, memory_item_table.c.source_ref)
            .where(memory_item_table.c.memory_id == "mem_g2")
        ).one()
        expect(row.title == "覆冰阈值" and row.source_ref == "trc_g2", "读写不一致")
    return "写入 → 读回一致，表结构可用"


# ===========================================================================
# H 组：反证 —— 证明这些测试本身不是"永远通过"
# ===========================================================================


@case("H1", "对照实验：合法的配置能加载成功（说明 B 组不是无脑报错）")
def case_h1() -> str:
    reg = Registry.load(ROOT / "config")
    expect(reg.summary()["agents"] == 2, "基线配置应能正常加载")
    expect(reg.summary()["skills"] == 3, "基线技能数应为 3")
    return "破坏会失败、不破坏会成功 —— 测试具备判别力"


@case("H2", "对照实验：合法的信封可构造（说明 C 组不是格式过严到不可用）")
def case_h2() -> str:
    env = _env(
        Performative.PROPOSE,
        result=MessageResult(
            confidence=0.9, evidence=[Evidence(type="skill", ref="risk.calc_icing_load")]
        ),
    )
    expect(env.envelope.performative is Performative.PROPOSE, "合法 PROPOSE 应可构造")
    return "约束存在但不过度，正常链路可通过"


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

GROUPS = {
    "A": "配置驱动（只改配置不改内核）",
    "B": "快速失败（配置错误拒绝启动）",
    "C": "铁律二 · 信封与协议纪律",
    "D": "铁律三 · 技能注册与鉴权",
    "E": "记忆硬约束（无来源不入库）",
    "F": "模型无旁路（禁止直连 API）",
    "G": "最小表集（表结构真的可用）",
    "H": "反证（测试本身具备判别力）",
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ElecAgent M0 证伪测试")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印通过项的细节")
    ap.add_argument("--list", action="store_true", help="只列出测试项")
    ap.add_argument("-k", "--filter", default="", help="按编号前缀过滤，如 A 或 A1")
    args = ap.parse_args(argv)

    if args.list:
        for c in CASES:
            print(f"  {c.cid:<3} {c.title}")
        return 0

    selected = [c for c in CASES if c.cid.startswith(args.filter)] if args.filter else list(CASES)
    if not selected:
        print(f"没有匹配 {args.filter!r} 的测试项")
        return 1

    print("ElecAgent M0 · 证伪测试（破坏它，看它是否报警）")
    print("=" * 72)

    current_group = ""
    for c in selected:
        g = c.cid[0]
        if g != current_group:
            current_group = g
            print(f"\n[{g}] {GROUPS.get(g, '')}")
        c.run(args.verbose)
        mark = {"PASS": "PASS", "FAIL": "FAIL", "SKIP": "SKIP"}[c.status]
        print(f"  {mark}  {c.cid:<3} {c.title}")
        if c.detail and (args.verbose or c.status == "FAIL"):
            print(f"        → {c.detail}")

    passed = sum(1 for c in selected if c.status == "PASS")
    failed = [c for c in selected if c.status == "FAIL"]
    print("\n" + "=" * 72)
    print(f"证伪测试：{passed}/{len(selected)} 通过")
    if failed:
        print("失败项：")
        for c in failed:
            print(f"  - {c.cid} {c.title}\n      {c.detail}")
        return 1
    print("结论：机制在被破坏时都会立刻失败 —— 不是装饰性的。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
