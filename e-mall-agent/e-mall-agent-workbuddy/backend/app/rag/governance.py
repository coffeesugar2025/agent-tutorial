"""知识治理（RAG 高阶层）：版本化、增量索引、撤销/回滚、租户隔离与审计。

内存实现，接口预留替换为真实向量库 + 元数据存储。所有操作都是确定性的，
不依赖外部服务。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from .ingest import Chunk


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _content_hash(content: str) -> str:
    return hashlib.blake2b((content or "").encode("utf-8"), digest_size=8).hexdigest()


# ---------------------------------------------------------------------------
# 审计
# ---------------------------------------------------------------------------
@dataclass
class AuditEntry:
    id: int
    action: str
    doc_id: str
    version: int | None
    tenant: str
    detail: str
    timestamp: str


class KnowledgeAudit:
    """记录 ingest / update / revoke / rollback 操作，可按条件查询。"""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._next_id = 1

    def log(self, action: str, doc_id: str, version: int | None,
            tenant: str, detail: str = "") -> AuditEntry:
        entry = AuditEntry(self._next_id, action, doc_id, version, tenant, detail, _now())
        self._next_id += 1
        self._entries.append(entry)
        return entry

    def query(self, action: str | None = None, doc_id: str | None = None,
              tenant: str | None = None) -> list[AuditEntry]:
        return [
            e for e in self._entries
            if (action is None or e.action == action)
            and (doc_id is None or e.doc_id == doc_id)
            and (tenant is None or e.tenant == tenant)
        ]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# 版本化存储
# ---------------------------------------------------------------------------
@dataclass
class Version:
    tenant: str
    doc_id: str
    version: int
    chunks: list[Chunk] = field(default_factory=list)
    category: str | None = None
    created_at: str = field(default_factory=_now)
    revoked: bool = False
    indexed: int = 0       # 本版本新增/变更并真正写入索引的 chunk 数
    unchanged: int = 0     # 与上一活动版本相同、跳过索引的 chunk 数

    @property
    def hashes(self) -> set[str]:
        return {_content_hash(c.content) for c in self.chunks}


@dataclass
class _IndexEntry:
    chunk: Chunk
    tenant: str
    doc_id: str
    version: int
    category: str | None


class VersionedStore:
    """按 ``(tenant, doc_id)`` 维护不可覆盖的版本链与当前活动索引。"""

    def __init__(self, default_tenant: str = "default",
                 audit: KnowledgeAudit | None = None) -> None:
        self.default_tenant = default_tenant
        self.audit = audit if audit is not None else KnowledgeAudit()
        self._versions: dict[tuple[str, str], list[Version]] = {}
        self._active: dict[tuple[str, str], int] = {}
        self._index: dict[tuple[str, str, str], _IndexEntry] = {}

    # -- 内部工具 ----------------------------------------------------------
    def _key(self, doc_id: str, tenant: str | None) -> tuple[str, str]:
        return (tenant or self.default_tenant, doc_id)

    def _list(self, key: tuple[str, str]) -> list[Version]:
        return self._versions.setdefault(key, [])

    def _get(self, key: tuple[str, str], version: int | None) -> Version | None:
        versions = self._list(key)
        if not versions:
            return None
        if version is None:
            version = self._active.get(key)
            if version is None:
                active = [v for v in versions if not v.revoked]
                version = active[-1].version if active else versions[-1].version
        return next((v for v in versions if v.version == version), None)

    @staticmethod
    def _coerce(chunks: Iterable[Chunk | dict[str, Any]]) -> list[Chunk]:
        result: list[Chunk] = []
        for item in chunks:
            if isinstance(item, Chunk):
                result.append(item)
                continue
            data = dict(item)
            content = str(data.get("content", ""))
            result.append(Chunk(
                id=str(data.get("id") or f"chunk-{_content_hash(content)[:12]}"),
                doc_id=str(data.get("doc_id", "")),
                content=content,
                metadata=dict(data.get("metadata") or {}),
                position=int(data.get("position", 0)),
            ))
        return result

    def _rebuild_index(self, key: tuple[str, str]) -> None:
        """从当前活动版本整体重建索引（回滚/撤销时使用）。"""
        for index_key in [k for k in self._index if k[:2] == key]:
            del self._index[index_key]
        tenant, doc_id = key
        version = self._get(key, None)
        if version is None or version.revoked:
            return
        for chunk in version.chunks:
            self._index[(tenant, doc_id, chunk.id)] = _IndexEntry(
                chunk, tenant, doc_id, version.version, version.category)

    # -- 公开 API ----------------------------------------------------------
    def ingest(
        self,
        doc_id: str,
        chunks: Iterable[Chunk | dict[str, Any]],
        *,
        tenant: str | None = None,
        category: str | None = None,
    ) -> Version:
        """新建文档版本（不覆盖旧版），仅把新增/变更 chunk 写入索引。"""
        key = self._key(doc_id, tenant)
        tenant_name = key[0]
        versions = self._list(key)
        previous = self._get(key, None)
        prev_hashes = previous.hashes if previous and not previous.revoked else set()

        new_chunks = self._coerce(chunks)
        version_no = max((v.version for v in versions), default=0) + 1
        version = Version(
            tenant=tenant_name, doc_id=doc_id, version=version_no,
            chunks=new_chunks, category=category,
        )
        versions.append(version)
        self._active[key] = version_no

        new_hashes = {_content_hash(c.content) for c in new_chunks}
        # 移除上一版本中被删除/修改的 chunk
        if previous is not None:
            for index_key, entry in list(self._index.items()):
                if (index_key[0], index_key[1]) == key and entry.version == previous.version:
                    if _content_hash(entry.chunk.content) not in new_hashes:
                        del self._index[index_key]

        # 增量索引：内容哈希已存在的 chunk 直接复用，不重复写入
        seen: set[str] = set()
        for chunk in new_chunks:
            digest = _content_hash(chunk.content)
            unchanged = digest in prev_hashes and digest not in seen
            seen.add(digest)
            if unchanged:
                version.unchanged += 1
                continue
            self._index[(tenant_name, doc_id, chunk.id)] = _IndexEntry(
                chunk, tenant_name, doc_id, version_no, category)
            version.indexed += 1

        action = "update" if previous is not None else "ingest"
        self.audit.log(action, doc_id, version_no, tenant_name,
                       f"chunks={len(new_chunks)} indexed={version.indexed} "
                       f"unchanged={version.unchanged}")
        return version

    def get_version(self, doc_id: str, version: int | None = None,
                    tenant: str | None = None) -> Version | None:
        return self._get(self._key(doc_id, tenant), version)

    def versions(self, doc_id: str, tenant: str | None = None) -> list[Version]:
        return list(self._list(self._key(doc_id, tenant)))

    def current_version(self, doc_id: str, tenant: str | None = None) -> int | None:
        version = self._get(self._key(doc_id, tenant), None)
        return version.version if version and not version.revoked else None

    def revoke(self, doc_id: str, version: int, tenant: str | None = None) -> bool:
        """撤销指定版本；若它是活动版本，回退到最近的未撤销版本。"""
        key = self._key(doc_id, tenant)
        target = self._get(key, version)
        if target is None or target.revoked:
            return False
        target.revoked = True
        if self._active.get(key) == version:
            remaining = [v for v in self._list(key) if not v.revoked]
            self._active[key] = remaining[-1].version if remaining else version
            self._rebuild_index(key)
        self.audit.log("revoke", doc_id, version, key[0], "版本已撤销")
        return True

    def rollback(self, doc_id: str, version: int, tenant: str | None = None) -> Version | None:
        """回滚到指定版本：其后的版本标记为撤销，并重建活动索引。"""
        key = self._key(doc_id, tenant)
        target = self._get(key, version)
        if target is None:
            return None
        for item in self._list(key):
            if item.version > version:
                item.revoked = True
        target.revoked = False
        self._active[key] = version
        self._rebuild_index(key)
        self.audit.log("rollback", doc_id, version, key[0], f"回滚到 v{version}")
        return target

    def active_chunks(
        self,
        doc_id: str | None = None,
        *,
        tenant: str | None = None,
        category: str | None = None,
    ) -> list[Chunk]:
        """查询当前活动索引中的 chunk，支持租户与类目隔离。"""
        tenant_name = tenant or self.default_tenant
        entries = [
            e for e in self._index.values()
            if e.tenant == tenant_name
            and (doc_id is None or e.doc_id == doc_id)
            and (category is None or e.category == category)
        ]
        return [e.chunk for e in sorted(entries, key=lambda e: (e.doc_id, e.chunk.position))]

    def indexed_chunk_ids(self, tenant: str | None = None) -> set[str]:
        tenant_name = tenant or self.default_tenant
        return {key[2] for key in self._index if key[0] == tenant_name}
