"""终止策略（纯函数，便于单测）。

一次 Agent 循环在每一步开始前调用 :func:`evaluate`，返回非 ``None`` 即终止。
判定顺序固定（先硬约束，后软约束），保证同一输入永远得到同一结论：

1. 超时 ``timeout``
2. 步数 ``max_steps``
3. token 预算 ``budget``
4. 循环（同工具同参数连续两次）``loop``
5. 无进展（连续两步信息摘要相同）``stalled``

> 顺序是契约的一部分：``tests/unit/test_termination.py`` 依赖它。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.state import (
    FINISH_BUDGET,
    FINISH_LOOP,
    FINISH_MAX_STEPS,
    FINISH_STALLED,
    FINISH_TIMEOUT,
)


@dataclass(slots=True)
class TerminationInput:
    """判定所需的全部输入。"""

    step: int
    tokens: int
    elapsed_seconds: float
    max_steps: int
    max_tokens: int
    timeout_seconds: float
    repeated_tool: bool = False
    stalled: bool = False


def detect_repeated_tool(signatures: list[str]) -> bool:
    """最近两次工具签名是否相同（同工具同参数连续调用）。

    只比较最近两次，不做全历史去重——同一工具在处理不同子任务时重复使用是合理的。
    """
    if len(signatures) < 2:
        return False
    return signatures[-1] == signatures[-2]


def detect_stall(progress_marks: list[str]) -> bool:
    """最近两步的信息摘要是否完全相同（没有产生新信息）。

    仅当已有至少 3 个标记时才判定，避免第 1、2 步就误杀。
    """
    if len(progress_marks) < 3:
        return False
    return progress_marks[-1] == progress_marks[-2]


def evaluate(data: TerminationInput) -> str | None:
    """返回终止原因；``None`` 表示可以继续。"""
    if data.elapsed_seconds >= data.timeout_seconds:
        return FINISH_TIMEOUT
    if data.step >= data.max_steps:
        return FINISH_MAX_STEPS
    if data.tokens >= data.max_tokens:
        return FINISH_BUDGET
    if data.repeated_tool:
        return FINISH_LOOP
    if data.stalled:
        return FINISH_STALLED
    return None


def fallback_answer(reason: str | None) -> str:
    """非正常终止时给用户的兜底话术（避免空白回复）。"""
    mapping = {
        FINISH_MAX_STEPS: "这个问题需要更多步骤才能处理完。我已经把目前查到的信息整理在上面了，"
        "你可以补充更具体的条件，或者我帮你转接人工客服继续处理。",
        FINISH_BUDGET: "这次对话的处理额度已经用完，为避免产生额外费用我先停下了。"
        "你可以把问题拆得更具体一些再问，或转接人工客服。",
        FINISH_TIMEOUT: "处理时间超出了限制。我已保留当前进度，你可以稍后继续，或转接人工客服。",
        FINISH_STALLED: "我多次尝试都没有获得新的有效信息，先停止以免继续消耗。"
        "建议补充订单号、商品名或更明确的条件。",
        FINISH_LOOP: "我发现自己重复调用了同一个操作，先停下避免死循环。"
        "建议把问题描述得更具体一些。",
    }
    return mapping.get(reason or "", "抱歉，这次没能帮你处理完，请稍后重试或转接人工客服。")


__all__ = [
    "TerminationInput",
    "detect_repeated_tool",
    "detect_stall",
    "evaluate",
    "fallback_answer",
]
