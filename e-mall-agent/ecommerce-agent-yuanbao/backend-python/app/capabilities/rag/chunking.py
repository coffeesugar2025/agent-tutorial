"""文档解析 / 切片 / 版本管理 / 增量索引 / 撤销。

覆盖 RAG 基础层与进阶层的「知识更新」链路：
  parse_document    txt / md / html 解析（html 去标签与脚本）
  split_text        fixed(char+overlap) / paragraph / sentence 三种切片
  DocumentStore     版本化文档仓库：add / update / delete / history / undo
  IncrementalIndex  只对新版本变化的 chunk 做 upsert/delete，产出 diff
"""
from __future__ import annotations

import hashlib
import html
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_TAG_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)
_SENT_RE = re.compile(r"(?<=[。！？.!?])\s+|\n+")


def parse_document(raw: str, fmt: str = "txt") -> str:
    if fmt not in ("txt", "md", "html"):
        raise ValueError("fmt 必须是 txt / md / html")
    text = raw or ""
    if fmt == "html":
        text = _TAG_RE.sub(" ", text)
        text = html.unescape(text)
    elif fmt == "md":
        text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)      # 图片
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)    # 链接保留文字
        text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return re.sub(r"[ \t]+", " ", text).strip()


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    version: int
    text: str
    start: int
    end: int
    tokens: int
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"chunk_id": self.chunk_id, "doc_id": self.doc_id,
                "version": self.version, "text": self.text,
                "start": self.start, "end": self.end, "tokens": self.tokens,
                "meta": self.meta}


def _cid(doc_id: str, idx: int, text: str) -> str:
    """id 由 (doc_id, 序号, 内容) 决定：内容不变 → id 稳定 → 增量索引可复用。"""
    h = hashlib.sha1(f"{doc_id}:{idx}:{text}".encode()).hexdigest()[:10]
    return f"{doc_id}#{idx:03d}-{h}"


def split_text(text: str, doc_id: str, version: int = 1,
               strategy: str = "fixed", chunk_size: int = 220,
               overlap: int = 40, meta: dict[str, Any] | None = None) -> list[Chunk]:
    """切片永远保留 offset，便于引用回溯到原文位置。"""
    if chunk_size <= overlap or chunk_size <= 0:
        raise ValueError("chunk_size 必须大于 overlap 且为正")
    units: list[tuple[int, int, str]] = []
    if strategy == "paragraph":
        pos = 0
        for m in re.finditer(r"[^\n]+(?:\n|$)", text):
            s = m.group().strip()
            if s:
                units.append((m.start(), m.end(), s))
        units = units or [(0, len(text), text)]
    elif strategy == "sentence":
        pos = 0
        for part in _SENT_RE.split(text):
            part = part.strip()
            if part:
                s = text.find(part, pos)
                units.append((s, s + len(part), part))
                pos = s + len(part)
        units = units or [(0, len(text), text)]
    elif strategy == "fixed":
        step = chunk_size - overlap
        for start in range(0, max(1, len(text)), step):
            units.append((start, min(len(text), start + chunk_size), text[start:start + chunk_size]))
    else:
        raise ValueError("strategy 必须是 fixed / paragraph / sentence")

    chunks: list[Chunk] = []
    buf = ""
    buf_start = 0
    for s, e, seg in units:
        if buf and len(buf) + len(seg) > chunk_size:
            chunks.append(Chunk(_cid(doc_id, len(chunks), buf), doc_id, version,
                                buf, buf_start, buf_start + len(buf), len(buf), meta or {}))
            tail = buf[-overlap:] if strategy == "fixed" else ""
            buf_start = buf_start + len(buf) - len(tail)
            buf = tail
        if not buf:
            buf_start = s
        buf += ("" if buf.endswith(" ") or not buf else " ") + seg if buf else seg
    if buf.strip():
        chunks.append(Chunk(_cid(doc_id, len(chunks), buf), doc_id, version,
                            buf, buf_start, buf_start + len(buf), len(buf), meta or {}))
    return chunks


@dataclass
class DocVersion:
    doc_id: str
    version: int
    text: str
    fmt: str
    meta: dict[str, Any]
    created_at: float = field(default_factory=time.time)


class DocumentStore:
    """版本化文档仓库 + 操作历史，支持 undo 回退到上一状态。"""

    def __init__(self) -> None:
        self._docs: dict[str, list[DocVersion]] = {}
        self._chunks: dict[str, dict[str, Chunk]] = {}
        self._version_chunks: dict[str, dict[int, dict[str, Chunk]]] = {}
        self._history: list[dict[str, Any]] = []
        self._lock = threading.RLock()

    def add(self, doc_id: str, text: str, fmt: str = "txt",
            strategy: str = "fixed", chunk_size: int = 220, overlap: int = 40,
            meta: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = parse_document(text, fmt)
        with self._lock:
            versions = self._docs.setdefault(doc_id, [])
            version = (versions[-1].version + 1) if versions else 1
            v = DocVersion(doc_id, version, parsed, fmt, meta or {})
            versions.append(v)
            chunks = split_text(parsed, doc_id, version, strategy, chunk_size, overlap, meta)
            cmap = {c.chunk_id: c for c in chunks}
            self._chunks[doc_id] = cmap
            self._version_chunks.setdefault(doc_id, {})[version] = dict(cmap)
            self._history.append({"op": "add", "doc_id": doc_id, "version": version,
                                  "at": time.time(), "chunk_ids": [c.chunk_id for c in chunks],
                                  "prev_chunks": []})
            return {"doc_id": doc_id, "version": version, "characters": len(parsed),
                    "chunks": [c.to_dict() for c in chunks]}

    def update(self, doc_id: str, text: str, **kw: Any) -> dict[str, Any]:
        with self._lock:
            prev = [c.chunk_id for c in self._chunks.get(doc_id, {}).values()]
        res = self.add(doc_id, text, **kw)
        self._history[-1]["op"] = "update"
        self._history[-1]["prev_chunks"] = prev
        diff = self.diff(doc_id)
        return {**res, "diff": diff}

    def diff(self, doc_id: str) -> dict[str, Any]:
        """版本间 chunk 差异：新增 / 删除 / 复用（内容未变则 chunk_id 稳定）。"""
        with self._lock:
            versions = self._docs.get(doc_id, [])
            snaps = self._version_chunks.get(doc_id, {})
            if not versions:
                return {"added": [], "removed": [], "reused": [], "version": 0}
            cur = set(self._chunks.get(doc_id, {}))
            prev = set(snaps.get(versions[-2].version, {})) if len(versions) >= 2 else set()
            return {"added": sorted(cur - prev), "removed": sorted(prev - cur),
                    "reused": sorted(cur & prev), "version": versions[-1].version}

    def delete(self, doc_id: str) -> dict[str, Any]:
        with self._lock:
            existing = self._chunks.pop(doc_id, {})
            removed = list(existing)
            objects = [c.to_dict() for c in existing.values()]
            docs = self._docs.pop(doc_id, [])
            snaps = self._version_chunks.pop(doc_id, {})
            self._history.append({"op": "delete", "doc_id": doc_id,
                                  "at": time.time(), "chunk_ids": [],
                                  "prev_chunks": removed,
                                  "prev_objects": objects,
                                  "prev_docs": docs, "prev_snaps": snaps})
            return {"doc_id": doc_id, "removed_chunks": removed}

    def undo(self) -> dict[str, Any]:
        """撤销最后一次操作：add 移除、delete 完整恢复、update 回退到上一版本切片。"""
        with self._lock:
            if not self._history:
                return {"ok": False, "error": "无可撤销操作"}
            last = self._history.pop()
            doc_id, op = last["doc_id"], last["op"]
            if op == "delete":
                restored = {}
                for d in last["prev_objects"]:
                    restored[d["chunk_id"]] = Chunk(
                        d["chunk_id"], d["doc_id"], d["version"], d["text"],
                        d["start"], d["end"], d["tokens"], d.get("meta", {}))
                self._chunks[doc_id] = restored
                self._docs[doc_id] = last["prev_docs"]
                self._version_chunks[doc_id] = last["prev_snaps"]
                return {"ok": True, "undone": op, "doc_id": doc_id,
                        "restored_chunks": list(restored)}
            if op == "add":
                self._chunks.pop(doc_id, None)
                self._docs.pop(doc_id, None)
                self._version_chunks.pop(doc_id, None)
                return {"ok": True, "undone": op, "doc_id": doc_id}
            versions = self._docs.get(doc_id, [])
            snaps = self._version_chunks.get(doc_id, {})
            if versions:
                versions.pop()
            if versions:
                self._chunks[doc_id] = dict(snaps.get(versions[-1].version, {}))
            else:
                self._chunks.pop(doc_id, None)
            return {"ok": True, "undone": op, "doc_id": doc_id,
                    "restored_version": versions[-1].version if versions else 0}

    def all_chunks(self) -> list[Chunk]:
        with self._lock:
            return [c for m in self._chunks.values() for c in m.values()]

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"op": h["op"], "doc_id": h["doc_id"], "at": h["at"]}
                    for h in self._history]

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {"documents": len(self._docs),
                    "chunks": sum(len(m) for m in self._chunks.values()),
                    "operations": len(self._history),
                    "versions": {d: [v.version for v in vs] for d, vs in self._docs.items()}}


class IncrementalIndex:
    """增量索引：只处理 diff 里的新增/删除，复用未变 chunk，避免全量重建。"""

    def __init__(self, store: DocumentStore | None = None) -> None:
        self.store = store or DocumentStore()
        self.indexed: set[str] = set()
        self._log: list[dict[str, Any]] = []

    def apply(self, doc_id: str) -> dict[str, Any]:
        diff = self.store.diff(doc_id)
        added = [c for c in diff["added"] if c not in self.indexed]
        removed = [c for c in diff["removed"] if c in self.indexed]
        self.indexed.update(added)
        self.indexed.difference_update(removed)
        self.indexed.update(diff["reused"])
        rec = {"doc_id": doc_id, "version": diff.get("version", 1),
               "upserted": added, "deleted": removed,
               "reused": len(diff["reused"])}
        self._log.append(rec)
        return rec

    def remove(self, doc_id: str) -> dict[str, Any]:
        chunks = [c for c in self.store.all_chunks() if c.doc_id == doc_id]
        ids = [c.chunk_id for c in chunks if c.chunk_id in self.indexed]
        self.indexed.difference_update(ids)
        return {"doc_id": doc_id, "deleted": ids}

    def stats(self) -> dict[str, Any]:
        return {"indexed_chunks": len(self.indexed), "operations": len(self._log),
                "last": self._log[-1] if self._log else None}


DOCS = DocumentStore()
INDEX = IncrementalIndex(DOCS)
