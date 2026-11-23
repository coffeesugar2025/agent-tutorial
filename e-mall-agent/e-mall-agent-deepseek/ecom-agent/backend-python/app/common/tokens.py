"""轻量 token 估算。

为什么不用 tiktoken：它会尝试下载 BPE 模型文件，离线/CI 环境必然失败。
这里用"中日韩字符按 1 token、拉丁字母/数字按 4 字符 1 token"的经验规则，
配合标点惩罚，误差对预算控制而言完全够用（仅用于预算/截断，不用于计费；
计费一律以模型返回的 usage 为准）。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
ASCII_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
PUNCT_RE = re.compile(r"[，。！？；：、,.!?;:（）()\[\]{}<>《》\"'·…—\-]+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；\n])")

# 每 token 对应的拉丁字符数（GPT/DeepSeek 系 BPE 的经验值）
CHARS_PER_TOKEN = 4.0
# 每条消息的角色/分隔开销
MESSAGE_OVERHEAD = 4


def estimate_tokens(text: str | None) -> int:
    """估算单段文本的 token 数，最少 0。"""
    if not text:
        return 0
    cjk = len(CJK_RE.findall(text))
    rest = text
    ascii_chars = 0
    for word in ASCII_WORD_RE.findall(rest):
        ascii_chars += len(word)
    punct = len(PUNCT_RE.findall(text))
    # 去掉中日韩、英文词、标点后剩余的字符（空白/emoji 等）按 2 字符 1 token
    remaining = max(len(text) - cjk - ascii_chars - punct, 0)
    total = cjk + ascii_chars / CHARS_PER_TOKEN + punct + remaining / 2.0
    return max(int(total + 0.5), 1 if text.strip() else 0)


def estimate_messages_tokens(messages: Iterable[object]) -> int:
    """估算消息列表的 token 数。

    支持两种输入：
    * LangChain ``BaseMessage``（读取 ``content``/``tool_calls``）；
    * ``(role, content)`` 二元组。
    """
    total = 0
    for item in messages:
        total += MESSAGE_OVERHEAD
        if isinstance(item, tuple) and len(item) == 2:
            total += estimate_tokens(str(item[1]))
            continue
        content = getattr(item, "content", None)
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, Sequence):
            for block in content:
                total += estimate_tokens(str(block))
        tool_calls = getattr(item, "tool_calls", None) or []
        for call in tool_calls:
            total += estimate_tokens(str(call.get("name", "")))
            total += estimate_tokens(str(call.get("args", "")))
    return total


def truncate_to_tokens(text: str, budget: int, suffix: str = "…") -> str:
    """按 token 预算截断文本，优先在句子边界截断。"""
    if budget <= 0:
        return ""
    if estimate_tokens(text) <= budget:
        return text
    sentences = [s for s in SENTENCE_SPLIT_RE.split(text) if s]
    kept: list[str] = []
    used = 0
    for sentence in sentences:
        cost = estimate_tokens(sentence)
        if used + cost > budget:
            break
        kept.append(sentence)
        used += cost
    if kept:
        return "".join(kept) + suffix
    # 单句过长：按字符比例硬截
    ratio = max(budget / max(estimate_tokens(text), 1), 0.0)
    cut = max(int(len(text) * ratio) - len(suffix), 0)
    return text[:cut] + suffix


def fit_texts(texts: Sequence[str], budget: int, separator: str = "\n\n") -> str:
    """按预算依次拼接多段文本，放不下的整段丢弃（不切断语义块）。"""
    kept: list[str] = []
    used = estimate_tokens(separator) * max(len(texts) - 1, 0) if texts else 0
    for text in texts:
        cost = estimate_tokens(text)
        if used + cost > budget:
            if not kept:
                kept.append(truncate_to_tokens(text, max(budget, 1)))
            break
        kept.append(text)
        used += cost
    return separator.join(kept)


def cost_in_cents(prompt_tokens: int, completion_tokens: int, price_in: float, price_out: float) -> int:
    """按"每百万 token 单价（分）"折算成本，向上取整到分。"""
    raw = prompt_tokens / 1_000_000 * price_in + completion_tokens / 1_000_000 * price_out
    return max(int(raw + 0.999), 0) if raw > 0 else 0


__all__ = [
    "CJK_RE",
    "cost_in_cents",
    "estimate_messages_tokens",
    "estimate_tokens",
    "fit_texts",
    "truncate_to_tokens",
]
