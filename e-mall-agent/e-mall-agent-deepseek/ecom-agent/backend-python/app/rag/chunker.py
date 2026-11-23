"""文档切片：递归切分 + 父子块（中文友好）。

策略：
1. 先按段落聚合成 **父块**（约 ``parent_size`` 字符），父块只用于"命中子块后回填上下文"；
2. 父块内再按语义分隔符（句号/问号/分号/换行）递归切 **子块**（约 ``size`` 字符，带重叠）；
3. 子块越界时按 ``overlap`` 回退，保证跨句语义不被切断得过于生硬。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from app.common.tokens import estimate_tokens

# 优先在语义边界切分（顺序即优先级）
SEPARATORS: tuple[str, ...] = ("\n\n", "\n", "。", "！", "？", "；", "!", "?", ";", "，", ",", " ")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_TRAILING_SPACE_RE = re.compile(r"[ \t]+\n")


@dataclass
class Chunk:
    """一个子块及其父块上下文。"""

    index: int
    content: str
    parent_content: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def checksum(self) -> str:
        return hashlib.sha1(self.content.encode("utf-8")).hexdigest()  # noqa: S324 - 仅用于去重


def clean_text(text: str) -> str:
    """清洗：去控制字符、压缩空行、统一换行、去行尾空格。"""
    if not text:
        return ""
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\u3000", " ").replace("\xa0", " ")
    cleaned = _CONTROL_RE.sub("", cleaned)
    cleaned = _TRAILING_SPACE_RE.sub("\n", cleaned)
    cleaned = _MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def _split_keep(text: str, separator: str) -> list[str]:
    """按分隔符切分并保留分隔符（避免句子被吞掉）。"""
    if not separator:
        return [text]
    parts = text.split(separator)
    result: list[str] = []
    for index, part in enumerate(parts):
        if index < len(parts) - 1:
            result.append(part + separator)
        elif part:
            result.append(part)
    return result


def split_recursive(text: str, size: int, separators: tuple[str, ...] = SEPARATORS) -> list[str]:
    """递归切分到不超过 ``size`` 字符的片段。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    for index, separator in enumerate(separators):
        if separator not in text:
            continue
        pieces = _split_keep(text, separator)
        if len(pieces) <= 1:
            continue
        merged: list[str] = []
        buffer = ""
        for piece in pieces:
            if len(piece) > size:
                if buffer:
                    merged.append(buffer)
                    buffer = ""
                merged.extend(split_recursive(piece, size, separators[index + 1 :]))
                continue
            if len(buffer) + len(piece) <= size:
                buffer += piece
            else:
                if buffer:
                    merged.append(buffer)
                buffer = piece
        if buffer:
            merged.append(buffer)
        return [item for item in merged if item.strip()]
    # 没有任何分隔符可用：硬切
    return [text[i : i + size] for i in range(0, len(text), size)]


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    """为相邻块增加重叠（从上一块尾部回退 overlap 个字符）。"""
    if overlap <= 0 or len(chunks) <= 1:
        return chunks
    result = [chunks[0]]
    for index in range(1, len(chunks)):
        tail = chunks[index - 1][-overlap:]
        candidate = tail + chunks[index]
        result.append(candidate)
    return result


def split_paragraphs(text: str, parent_size: int) -> list[str]:
    """按空行聚合成父块（超长段落再按句号切）。"""
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    parents: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > parent_size:
            pieces = split_recursive(paragraph, parent_size, SEPARATORS[2:])
        else:
            pieces = [paragraph]
        for piece in pieces:
            if len(buffer) + len(piece) + 2 <= parent_size:
                buffer = f"{buffer}\n\n{piece}" if buffer else piece
            else:
                if buffer:
                    parents.append(buffer)
                buffer = piece
    if buffer:
        parents.append(buffer)
    return parents or ([text] if text else [])


def chunk_document(
    text: str,
    *,
    size: int = 400,
    overlap: int = 80,
    parent_size: int = 1200,
    metadata: dict[str, Any] | None = None,
) -> list[Chunk]:
    """主入口：文本 → 子块列表（带父块内容与元信息）。"""
    cleaned = clean_text(text)
    if not cleaned:
        return []
    base_meta = dict(metadata or {})
    chunks: list[Chunk] = []
    index = 0
    for parent_index, parent in enumerate(split_paragraphs(cleaned, parent_size)):
        raw_chunks = split_recursive(parent, size)
        raw_chunks = _apply_overlap(raw_chunks, overlap)
        for piece in raw_chunks:
            content = piece.strip()
            if not content:
                continue
            chunk_meta = dict(base_meta)
            chunk_meta.update({"parentIndex": parent_index, "chars": len(content)})
            chunks.append(
                Chunk(
                    index=index,
                    content=content,
                    parent_content=parent,
                    token_count=estimate_tokens(content),
                    metadata=chunk_meta,
                )
            )
            index += 1
    return chunks


def chunk_stats(chunks: list[Chunk]) -> dict[str, Any]:
    """切片质量指标（调试/评测用）。"""
    if not chunks:
        return {"count": 0, "avgChars": 0, "avgTokens": 0, "maxChars": 0}
    lengths = [len(chunk.content) for chunk in chunks]
    return {
        "count": len(chunks),
        "avgChars": round(sum(lengths) / len(lengths), 1),
        "avgTokens": round(sum(chunk.token_count for chunk in chunks) / len(chunks), 1),
        "maxChars": max(lengths),
        "minChars": min(lengths),
    }


__all__ = [
    "SEPARATORS",
    "Chunk",
    "chunk_document",
    "chunk_stats",
    "clean_text",
    "split_paragraphs",
    "split_recursive",
]
