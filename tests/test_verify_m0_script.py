"""元测试：验证 `scripts/verify_m0.py` 本身具备判别力。

为什么需要这一层：
    证伪测试的价值完全取决于「它能不能失败」。
    如果脚本里的 expect() 写错、异常被吞掉、或者断言恒为真，
    那么 35/35 全绿是**假绿**。

本文件做两件事：
    1. 脚本整体退出码必须为 0（35 项全部通过）
    2. **故意制造破坏**：用 monkeypatch 让某条证伪测试在"机制未报警"时
       仍然通过 —— 必须被脚本自己判为 FAIL 并返回非零退出码
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_m0.py"


def _load_script():
    """把 verify_m0.py 作为模块加载，便于直接操作其内部对象。"""
    spec = importlib.util.spec_from_file_location("verify_m0_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["verify_m0_under_test"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_script_exits_zero() -> None:
    """脚本整体必须全绿并返回 0。"""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "35/35 通过" in proc.stdout, proc.stdout[-800:]


def test_script_lists_all_cases() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert proc.returncode == 0
    out = proc.stdout
    for cid in ("A1", "B1", "C1", "D1", "E1", "F1", "G1", "H1"):
        assert cid in out, f"{cid} 未出现在测试项列表中"


def test_script_filter_works() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "-k", "C"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
    )
    assert proc.returncode == 0
    assert "6/6 通过" in proc.stdout, proc.stdout[-400:]


def test_expect_raises_fails_when_nothing_is_raised() -> None:
    """核心判别力：机制不报警时，expect_raises 必须判 FAIL。"""
    mod = _load_script()
    with pytest.raises(mod.Failure) as excinfo:
        mod.expect_raises((ValueError,), lambda: 1 + 1, "应拒绝")
    assert "机制可能是装饰性的" in str(excinfo.value)


def test_expect_fails_on_false_condition() -> None:
    mod = _load_script()
    with pytest.raises(mod.Failure):
        mod.expect(False, "条件不成立")


def test_case_records_failure_status() -> None:
    """Case 在断言失败时必须标记 FAIL，而非默默 PASS。"""

    def broken_mechanism() -> str:
        # 模拟「机制没有报警」：期望抛错但没抛
        mod.expect_raises((ValueError,), lambda: "no error", "应拒绝")
        return "unreachable"

    mod = _load_script()
    c = mod.Case("X1", "模拟失效机制", broken_mechanism)
    c.run(verbose=False)
    assert c.status == "FAIL"
    assert "装饰性" in c.detail


def test_case_passes_on_healthy_mechanism() -> None:
    def healthy() -> str:
        mod.expect_raises((ValueError,), lambda: (_ for _ in ()).throw(ValueError("拒绝")), "应拒绝")
        return "ok"

    mod = _load_script()
    c = mod.Case("X2", "模拟正常机制", healthy)
    c.run(verbose=False)
    assert c.status == "PASS"
    assert c.detail == "ok"


def test_c1_detects_a_disabled_mechanism(monkeypatch: pytest.MonkeyPatch) -> None:
    """C1 必须能识别「机制被写假」。

    做法：把 C1 内部调用的构造函数替换成一个不做校验的假构造函数
    （模拟"约束只写在文档里、代码没实装"），C1 必须转为 FAIL。

    为什么不用 monkeypatch 改 pydantic 方法：
    pydantic v2 把校验器编译进了 Rust 核心 schema，替换 Python 层的
    `model_validate` 等方法不会改变实际行为（已验证），因此这里替换的是
    **被测代码所依赖的构造入口**，这正是「机制缺失」的等价情形。
    """
    mod = _load_script()
    from contracts import Envelope, EnvelopeHeader

    def unvalidated(**kwargs):  # noqa: ANN003
        """不做任何校验的假构造器 —— 等价于约束未实装。"""
        return Envelope.model_construct(
            envelope=kwargs.get("envelope") or EnvelopeHeader(
                trace_id="t", sender="s", receiver="r",
                performative=mod.Performative.PROPOSE, intent="i",
            ),
            payload=kwargs.get("payload", {}),
            context_refs=kwargs.get("context_refs", mod.ContextRefs()),
            constraints=kwargs.get("constraints", mod.Constraints()),
            result=kwargs.get("result", mod.MessageResult()),
            telemetry=kwargs.get("telemetry", mod.Telemetry()),
            security=kwargs.get("security", mod.Security()),
        )

    monkeypatch.setattr(mod, "Envelope", unvalidated)

    c1 = next(c for c in mod.CASES if c.cid == "C1")
    c1.run(verbose=False)
    assert c1.status == "FAIL", (
        "约束失效后 C1 仍通过 —— C 组不具备判别力（断言恒真）"
    )
    assert "装饰性" in c1.detail, f"失败原因不够明确：{c1.detail}"

    # 恢复真实实现后必须重新变绿，确认测试无副作用
    monkeypatch.undo()
    c1_again = next(c for c in mod.CASES if c.cid == "C1")
    c1_again.run(verbose=False)
    assert c1_again.status == "PASS", "恢复机制后 C1 仍未通过，说明存在状态污染"


def test_c3_detects_a_disabled_mechanism(monkeypatch: pytest.MonkeyPatch) -> None:
    """C3（REFUSE 必带理由）同样必须具备判别力。"""
    mod = _load_script()
    from contracts import Envelope, EnvelopeHeader

    def unvalidated(**kwargs):  # noqa: ANN003
        return Envelope.model_construct(
            envelope=EnvelopeHeader(
                trace_id="t", sender="s", receiver="r",
                performative=mod.Performative.REFUSE, intent="i",
            ),
            payload={}, context_refs=mod.ContextRefs(), constraints=mod.Constraints(),
            result=mod.MessageResult(), telemetry=mod.Telemetry(), security=mod.Security(),
        )

    monkeypatch.setattr(mod, "Envelope", unvalidated)
    c3 = next(c for c in mod.CASES if c.cid == "C3")
    c3.run(verbose=False)
    assert c3.status == "FAIL", "静默拒绝未被拦截 —— C 组不具备判别力"


def test_b2_detects_a_disabled_mechanism(monkeypatch: pytest.MonkeyPatch) -> None:
    """B2（未注册技能被拒）必须具备判别力：把校验摘掉后必须 FAIL。"""
    mod = _load_script()
    from runtime.registry import Registry

    original = Registry._validate  # noqa: SLF001 - 有意访问
    monkeypatch.setattr(Registry, "_validate", lambda self, *a, **k: None)

    c = next(c for c in mod.CASES if c.cid == "B2")
    c.run(verbose=False)
    assert c.status == "FAIL", "校验被摘除后 B2 仍通过 —— B 组不具备判别力"

    monkeypatch.undo()
    monkeypatch.setattr(Registry, "_validate", original)
    c_again = next(c for c in mod.CASES if c.cid == "B2")
    c_again.run(verbose=False)
    assert c_again.status == "PASS", "恢复校验后 B2 仍未通过"


def test_e1_detects_a_disabled_mechanism(monkeypatch: pytest.MonkeyPatch) -> None:
    """E1（无来源不入库）必须具备判别力。"""
    mod = _load_script()
    from contracts import MemoryItem

    def unvalidated(**kwargs):  # noqa: ANN003
        return MemoryItem.model_construct(**kwargs)

    monkeypatch.setattr(mod, "MemoryItem", unvalidated)
    c = next(c for c in mod.CASES if c.cid == "E1")
    c.run(verbose=False)
    assert c.status == "FAIL", "硬约束被摘除后 E1 仍通过 —— E 组不具备判别力"


def test_script_group_counts_are_nonzero() -> None:
    """每个分组都必须有测试用例，避免分组名存在但内容为空。"""
    mod = _load_script()
    for g in ("A", "B", "C", "D", "E", "F", "G", "H"):
        n = sum(1 for c in mod.CASES if c.cid.startswith(g))
        assert n > 0, f"分组 {g} 没有任何用例"
