"""终止策略单元测试：覆盖 docs/00 §5 的 7 条终止条件与优先级。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-17] 评测与迭代  （支撑）
# 职责：终止策略单元测试：覆盖 docs/00 §5 的 7 条终止条件与优先级
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

from app.agents.state import (
    FINISH_BUDGET,
    FINISH_LOOP,
    FINISH_MAX_STEPS,
    FINISH_STALLED,
    FINISH_TIMEOUT,
)
from app.agents.termination import (
    TerminationInput,
    detect_repeated_tool,
    detect_stall,
    evaluate,
    fallback_answer,
)


def _input(**overrides) -> TerminationInput:
    base = {
        "step": 1,
        "tokens": 100,
        "elapsed_seconds": 1.0,
        "max_steps": 12,
        "max_tokens": 60000,
        "timeout_seconds": 120,
        "repeated_tool": False,
        "stalled": False,
    }
    base.update(overrides)
    return TerminationInput(**base)


def test_continue_when_all_under_limit():
    assert evaluate(_input()) is None


def test_timeout():
    assert evaluate(_input(elapsed_seconds=120)) == FINISH_TIMEOUT


def test_max_steps():
    assert evaluate(_input(step=12)) == FINISH_MAX_STEPS


def test_budget():
    assert evaluate(_input(tokens=60000)) == FINISH_BUDGET


def test_loop():
    assert evaluate(_input(repeated_tool=True)) == FINISH_LOOP


def test_stalled():
    assert evaluate(_input(stalled=True)) == FINISH_STALLED


def test_priority_timeout_before_everything():
    """超时优先级最高：即使同时触发其他条件也只报 timeout。"""
    data = _input(
        elapsed_seconds=999,
        step=99,
        tokens=10**9,
        repeated_tool=True,
        stalled=True,
    )
    assert evaluate(data) == FINISH_TIMEOUT


def test_priority_order_step_before_budget():
    assert evaluate(_input(step=99, tokens=10**9)) == FINISH_MAX_STEPS


def test_priority_budget_before_loop():
    assert evaluate(_input(tokens=10**9, repeated_tool=True, stalled=True)) == FINISH_BUDGET


def test_detect_repeated_tool():
    assert detect_repeated_tool([]) is False
    assert detect_repeated_tool(["a"]) is False
    assert detect_repeated_tool(["a", "b"]) is False
    assert detect_repeated_tool(["a", "a"]) is True
    assert detect_repeated_tool(["a", "b", "b"]) is True


def test_detect_stall_requires_three_marks():
    assert detect_stall([]) is False
    assert detect_stall(["x", "x"]) is False
    # 至少 3 个标记才判定，避免前两步误杀
    assert detect_stall(["x", "x", "x"]) is True
    assert detect_stall(["x", "y", "y"]) is True
    assert detect_stall(["x", "y", "z"]) is False


def test_fallback_answer_never_empty():
    for reason in (FINISH_MAX_STEPS, FINISH_BUDGET, FINISH_TIMEOUT, FINISH_STALLED, FINISH_LOOP):
        text = fallback_answer(reason)
        assert isinstance(text, str) and len(text) > 10
    assert fallback_answer(None)
