"""文档解析与切片（RAG 基础层）。

- 解析器：纯文本 / Markdown（按标题层级）/ JSON（按记录）。
- 切片策略：固定长度 + overlap、按章节、按语义段落。

生产环境可把解析器替换为 PDF/DOCX/网页解析器，只要继续产出 ``Section``，
``Chunker`` 的接口保持不变。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

SUPPORTED_FORMATS = ("text", "markdown", "json")
SUPPORTED_STRATEGIES = ("fixed", "section", "paragraph")


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class Chunk:
    """一个可检索的文本块。"""

    id: str
    doc_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    position: int = 0


@dataclass
class Section:
    """解析后的逻辑段落，携带来源元数据（标题路径 / 记录序号等）。"""

    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    """待解析的原始文档。"""

    doc_id: str
    content: str
    format: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)


def _make_chunk_id(doc_id: str, position: int, content: str) -> str:
    digest = hashlib.blake2b(
        f"{doc_id}:{position}:{content}".encode("utf-8"), digest_size=8
    ).hexdigest()
    return f"{doc_id}-{position}-{digest}"


# ---------------------------------------------------------------------------
# 解析器：raw content -> list[Section]
# ---------------------------------------------------------------------------
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*$")


def parse_text(content: str, **meta: Any) -> list[Section]:
    """纯文本：整篇作为一个 section。"""
    text = (content or "").strip()
    return [Section(text, dict(meta))] if text else []


def parse_markdown(content: str, **meta: Any) -> list[Section]:
    """Markdown：按 ``#`` 标题层级切，标题行并入对应 section 的正文。

    每个 section 的 metadata 含 ``heading``（完整标题路径）、``heading_title``
    与 ``level``（标题层级），供按章节检索与溯源使用。
    """
    sections: list[Section] = []
    lines: list[str] = []
    stack: list[tuple[int, str]] = []
    current_meta: dict[str, Any] = dict(meta)

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            sections.append(Section(text, dict(current_meta)))
        lines.clear()

    for raw_line in (content or "").splitlines():
        match = _HEADING_RE.match(raw_line)
        if match:
            flush()
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            current_meta = {
                **meta,
                "heading": " > ".join(t for _, t in stack),
                "heading_title": title,
                "level": level,
            }
        lines.append(raw_line)
    flush()
    return sections


def parse_json(content: str, **meta: Any) -> list[Section]:
    """JSON：按记录切。支持记录数组，或含 records/docs/data 等键的对象。

    每条记录转成可读文本（``key: value``），原始记录保存在
    metadata["record"]，记录序号保存在 metadata["record_index"]。
    """
    try:
        data = json.loads(content or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError("JSON 文档解析失败") from exc

    if isinstance(data, dict):
        for key in ("records", "docs", "documents", "data", "items", "rows"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]
    if not isinstance(data, list):
        data = [data]

    sections: list[Section] = []
    for index, record in enumerate(data):
        if isinstance(record, dict):
            text = "\n".join(f"{key}: {value}" for key, value in record.items())
        else:
            text = str(record)
        if text.strip():
            sections.append(Section(
                text.strip(),
                {**meta, "record_index": index, "record": record},
            ))
    return sections


_PARSERS = {
    "text": parse_text,
    "markdown": parse_markdown,
    "json": parse_json,
}


def parse_document(doc: Document) -> list[Section]:
    """根据 ``doc.format`` 分派到对应解析器。"""
    parser = _PARSERS.get(doc.format)
    if parser is None:
        raise ValueError(
            f"不支持的文档格式: {doc.format}（可选 {', '.join(SUPPORTED_FORMATS)}）"
        )
    return parser(doc.content, **doc.metadata)


# ---------------------------------------------------------------------------
# 切片策略
# ---------------------------------------------------------------------------
def _split_fixed(text: str, size: int, overlap: int) -> list[str]:
    """按字符切成长度 <= size 的片段，相邻片段重叠 overlap 个字符。"""
    if not text:
        return []
    pieces: list[str] = []
    step = size - overlap
    start = 0
    while start < len(text):
        piece = text[start:start + size].strip()
        if piece:
            pieces.append(piece)
        if start + size >= len(text):
            break
        start += step
    return pieces


class Chunker:
    """把文档切成带位置与元数据的 ``Chunk`` 列表。

    Args:
        strategy: ``fixed``（固定长度 + overlap）/ ``section``（按章节）/
            ``paragraph``（按语义段落）。
        chunk_size: 每块最大字符数。
        overlap: fixed 策略相邻块的重叠字符数（会被限制在 [0, size-1]）。
    """

    def __init__(self, strategy: str = "fixed", chunk_size: int = 200,
                 overlap: int = 40) -> None:
        if strategy not in SUPPORTED_STRATEGIES:
            raise ValueError(
                f"不支持的切片策略: {strategy}（可选 {', '.join(SUPPORTED_STRATEGIES)}）"
            )
        if chunk_size <= 0:
            raise ValueError("chunk_size 必须为正整数")
        self.strategy = strategy
        self.chunk_size = chunk_size
        self.overlap = max(0, min(overlap, chunk_size - 1))

    def chunk(
        self,
        doc: Document | str,
        doc_id: str | None = None,
        format: str = "text",
        metadata: dict[str, Any] | None = None,
    ) -> list[Chunk]:
        """切片入口。``doc`` 可传 ``Document`` 或裸字符串。"""
        if isinstance(doc, str):
            doc = Document(
                doc_id=doc_id or "doc",
                content=doc,
                format=format,
                metadata=metadata or {},
            )
        sections = parse_document(doc)
        if not sections:
            return []

        if self.strategy == "fixed":
            return self._fixed(doc, sections)
        if self.strategy == "section":
            return self._section(doc, sections)
        return self._paragraph(doc, sections)

    # -- 内部实现 ----------------------------------------------------------
    def _build(self, doc: Document, position: int, text: str,
               meta: dict[str, Any]) -> Chunk:
        return Chunk(
            id=_make_chunk_id(doc.doc_id, position, text),
            doc_id=doc.doc_id,
            content=text,
            metadata={**meta, "strategy": self.strategy},
            position=position,
        )

    def _fixed(self, doc: Document, sections: list[Section]) -> list[Chunk]:
        text = "\n\n".join(s.content for s in sections)
        chunks: list[Chunk] = []
        for position, piece in enumerate(_split_fixed(text, self.chunk_size, self.overlap)):
            chunks.append(self._build(doc, position, piece, {"source_format": doc.format}))
        return chunks

    def _section(self, doc: Document, sections: list[Section]) -> list[Chunk]:
        chunks: list[Chunk] = []
        position = 0
        for section in sections:
            pieces = (
                [section.content]
                if len(section.content) <= self.chunk_size
                else _split_fixed(section.content, self.chunk_size, self.overlap)
            )
            for piece in pieces:
                text = piece.strip()
                if text:
                    chunks.append(self._build(doc, position, text, section.metadata))
                    position += 1
        return chunks

    def _paragraph(self, doc: Document, sections: list[Section]) -> list[Chunk]:
        chunks: list[Chunk] = []
        position = 0
        for section in sections:
            paragraphs = [
                p.strip() for p in re.split(r"\n\s*\n", section.content) if p.strip()
            ]
            buffer: list[str] = []
            for para in paragraphs:
                pieces = (
                    [para]
                    if len(para) <= self.chunk_size
                    else _split_fixed(para, self.chunk_size, self.overlap)
                )
                for piece in pieces:
                    piece = piece.strip()
                    if not piece:
                        continue
                    if buffer and len("\n\n".join(buffer)) + len(piece) + 2 > self.chunk_size:
                        text = "\n\n".join(buffer)
                        chunks.append(self._build(doc, position, text, section.metadata))
                        position += 1
                        buffer = []
                    buffer.append(piece)
            if buffer:
                text = "\n\n".join(buffer)
                chunks.append(self._build(doc, position, text, section.metadata))
                position += 1
        return chunks


def chunk_document(
    doc: Document | str,
    strategy: str = "fixed",
    chunk_size: int = 200,
    overlap: int = 40,
    **kwargs: Any,
) -> list[Chunk]:
    """便捷函数：一步完成解析与切片。"""
    return Chunker(strategy=strategy, chunk_size=chunk_size, overlap=overlap).chunk(
        doc, **kwargs
    )
