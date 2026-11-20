"""文本与 Token 工具。

教程里的所有 Token 数字都是「估算值」：中文按 1 字 ≈ 1 token，英文按 4 字符 ≈ 1 token。
真实计费请以模型厂商返回的 usage 为准。估算的意义在于：让上下文预算、成本优化这些
工程动作可以被观察、被比较。
"""

from __future__ import annotations

import json
import re

_CJK = re.compile(r"[\u4e00-\u9fff]")


def estimate_tokens(text: str) -> int:
    """估算一段文本的 token 数（不追求精确，追求稳定、可解释）。"""
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return cjk + (other + 3) // 4


def messages_tokens(messages: list[dict]) -> int:
    """估算一整组 messages 的 token 数，包含角色标记与工具调用的开销。"""
    total = 0
    for message in messages:
        total += 4  # 每条消息的角色/分隔符开销
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        total += estimate_tokens(content)
        for call in message.get("tool_calls") or []:
            total += estimate_tokens(json.dumps(call, ensure_ascii=False))
        if message.get("name"):
            total += estimate_tokens(str(message["name"]))
    return total


def truncate_tokens(text: str, max_tokens: int, suffix: str = "…") -> str:
    """按估算 token 截断文本，尽量保留开头。"""
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_tokens(text[:mid]) <= max_tokens:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + suffix


_SEPARATORS = ("\n\n", "\n", "。", "！", "？", "；", "，", " ")


def chunk_text(text: str, chunk_size: int = 400, overlap: int = 60) -> list[str]:
    """按字符数切分文本，优先在段落/句子边界断开，并保留少量重叠。

    chunk_size 与 overlap 都以「字符」为单位。中文场景下 1 字符约等于 1 token，
    所以 400 字符大约是 400 token，适合作为教学默认值。
    """
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    if chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 0")
    overlap = max(0, min(overlap, chunk_size // 2))

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            window = text[start:end]
            cut = max(window.rfind(sep) for sep in _SEPARATORS)
            if cut >= int(chunk_size * 0.55):
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks


def chunk_markdown(text: str, max_chars: int = 500) -> list[dict]:
    """按 Markdown 标题切分，返回带 heading 元数据的块。

    这是 RAG 章节最常用的切片方式：先按语义层级（章节）切，再按长度切。
    """
    text = (text or "").replace("\r\n", "\n").strip()
    sections: list[tuple[str, list[str]]] = []
    heading, buffer = "", []
    for line in text.splitlines():
        if line.startswith("#"):
            if any(item.strip() for item in buffer):
                sections.append((heading, buffer))
            buffer = []
            if line.startswith("## "):
                heading = line[3:].strip()
        else:
            buffer.append(line)
    if any(item.strip() for item in buffer):
        sections.append((heading, buffer))

    result: list[dict] = []
    index = 0
    for heading, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        for piece in chunk_text(body, chunk_size=max_chars, overlap=min(60, max_chars // 5)):
            result.append({"text": piece, "heading": heading, "index": index})
            index += 1
    return result


def mask_pii(text: str) -> str:
    """对手机号、邮箱、身份证号做简单脱敏，演示用。"""
    text = re.sub(r"(1[3-9]\d)(\d{4})(\d{4})", r"\1****\3", text)
    text = re.sub(r"([\w.+-]{1,3})[\w.+-]*(@[\w.-]+)", r"\1***\2", text)
    text = re.sub(r"(\d{6})(\d{8})(\d{3}[\dXx])", r"\1********\3", text)
    return text
