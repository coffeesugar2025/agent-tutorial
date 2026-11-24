"""上下文组装：去重 → 排序 → token 预算 → 引用标注 + 不可信数据隔离。

输出结构与模型约定：
``[1] 《标题》 (docId=2, chunkId=88, score=0.87)`` 后紧跟 ``<untrusted_data>`` 块，
模型在正文中可用 ``[1]`` 形式引用；``citations`` 与编号一一对应，供 SSE ``citation`` 事件。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-12] 检索增强 RAG
# 职责：上下文组装：去重 → 排序 → token 预算 → 引用标注 + 不可信数据隔离
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from app.common.tokens import estimate_tokens, truncate_to_tokens
from app.security.injection import UNTRUSTED_NOTICE, wrap_untrusted


@dataclass
class AssembledContext:
    """组装结果。"""

    text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    token_used: int = 0
    item_count: int = 0
    dropped: int = 0
    notice: str = UNTRUSTED_NOTICE

    @property
    def empty(self) -> bool:
        return self.item_count == 0

    def to_prompt_block(self) -> str:
        if not self.text:
            return ""
        return f"{self.text}"


def _parent_key(item: Any) -> str:
    parent = getattr(item, "parent_content", "") or ""
    if parent:
        return hashlib.sha1(parent.encode("utf-8")).hexdigest()  # noqa: S324 - 仅去重
    return f"chunk:{getattr(item, 'chunk_id', 0)}"


def assemble(
    items: list[Any],
    token_budget: int = 1800,
    *,
    query: str = "",
    include_notice: bool = True,
) -> AssembledContext:
    """把检索结果组装为可直接注入 prompt 的上下文。"""
    if not items:
        return AssembledContext()

    ordered = sorted(
        items,
        key=lambda item: (
            getattr(item, "rerank_score", None) if getattr(item, "rerank_score", None) is not None else 0.0,
            getattr(item, "score", 0.0),
        ),
        reverse=True,
    )

    blocks: list[str] = []
    citations: list[dict[str, Any]] = []
    used = 0
    dropped = 0
    seen: set[str] = set()

    if include_notice:
        blocks.append(UNTRUSTED_NOTICE)
        used += estimate_tokens(UNTRUSTED_NOTICE)

    for item in ordered:
        key = _parent_key(item)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)

        content = getattr(item, "content", "") or ""
        parent = getattr(item, "parent_content", "") or ""
        body = parent if len(parent) <= 1200 else truncate_to_tokens(parent, 600)
        if not body:
            body = content
        head = (
            f"[{len(citations) + 1}] 《{getattr(item, 'title', '未命名')}》"
            f"（docId={getattr(item, 'document_id', 0)}, chunkId={getattr(item, 'chunk_id', 0)}, "
            f"score={round(float(getattr(item, 'score', 0.0)), 3)}）"
        )
        wrapped = wrap_untrusted(
            body, source=f"knowledge:{getattr(item, 'document_id', 0)}", kind="document"
        )
        block = f"{head}\n{wrapped}"
        cost = estimate_tokens(block)
        if used + cost > token_budget:
            remaining = token_budget - used
            if remaining > 120 and not blocks:
                body = truncate_to_tokens(body, remaining // 2)
                block = f"{head}\n{wrap_untrusted(body, source='knowledge', kind='document')}"
                cost = estimate_tokens(block)
            else:
                dropped += len(ordered) - len(citations)
                break
        blocks.append(block)
        used += cost
        citations.append(
            {
                "docId": getattr(item, "document_id", 0),
                "chunkId": getattr(item, "chunk_id", 0),
                "title": getattr(item, "title", ""),
                "snippet": getattr(item, "snippet", "") or content[:180],
                "score": round(float(getattr(item, "score", 0.0)), 4),
            }
        )

    return AssembledContext(
        text="\n\n".join(blocks),
        citations=citations,
        token_used=used,
        item_count=len(citations),
        dropped=max(dropped, 0),
    )


def citation_marker(index: int) -> str:
    """正文引用标记。"""
    return f"[{index}]"


__all__ = ["AssembledContext", "assemble", "citation_marker"]
