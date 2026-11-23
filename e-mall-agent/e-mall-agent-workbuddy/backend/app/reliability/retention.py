"""数据保留策略与统一删除编排。

``RetentionPolicy`` 按数据类型配置 TTL，``RetentionManager.purge_expired`` 清理
过期记录，``delete_user_data`` 统一编排：调用现有 ``MemoryManager.forget_user``
与 ``AuditLogger.record``，只调用不修改其实现。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..memory.manager import MemoryManager
from ..security.audit import AuditLogger


@dataclass
class RetentionRecord:
    """一条纳入保留策略管理的记录。"""

    id: str
    data_type: str
    user_id: str
    created_at: float
    payload: Any = None


@dataclass
class RetentionPolicy:
    """按数据类型配置保留时长（秒）。未配置类型使用 ``default_ttl``。"""

    ttls: dict[str, float] = field(default_factory=dict)
    default_ttl: float | None = None

    def ttl_for(self, data_type: str) -> float | None:
        return self.ttls.get(data_type, self.default_ttl)

    def is_expired(self, created_at: float, data_type: str,
                   now: float | None = None) -> bool:
        ttl = self.ttl_for(data_type)
        if ttl is None or ttl <= 0:
            return False
        current = time.time() if now is None else now
        return current - created_at >= ttl


@runtime_checkable
class MemoryLike(Protocol):
    def forget_user(self, user_id: str) -> dict[str, int]: ...


@runtime_checkable
class AuditLike(Protocol):
    def record(self, actor: str, action: str, resource: str,
               decision: str = "allow", detail: str = "") -> dict[str, Any]: ...


class RetentionManager:
    """保留策略执行器 + 用户数据删除统一编排入口。"""

    def __init__(
        self,
        policy: RetentionPolicy | None = None,
        memory: MemoryLike | None = None,
        audit: AuditLike | None = None,
        *,
        actor: str = "retention-manager",
        clock: Any = None,
    ) -> None:
        self.policy = policy or RetentionPolicy()
        self.memory = memory if memory is not None else MemoryManager()
        self.audit = audit if audit is not None else AuditLogger()
        self.actor = actor
        self._clock = clock or time.time
        self._records: dict[str, RetentionRecord] = {}
        self._seq = 0

    def add(self, data_type: str, user_id: str, payload: Any = None,
            created_at: float | None = None) -> RetentionRecord:
        self._seq += 1
        record = RetentionRecord(
            id=f"ret-{self._seq}", data_type=data_type, user_id=user_id,
            created_at=self._clock() if created_at is None else created_at,
            payload=payload,
        )
        self._records[record.id] = record
        return record

    def records_for(self, user_id: str) -> list[RetentionRecord]:
        return [r for r in self._records.values() if r.user_id == user_id]

    def __len__(self) -> int:
        return len(self._records)

    def purge_expired(self, now: float | None = None) -> int:
        """删除所有过期记录，逐条写审计，返回清理条数。"""
        current = self._clock() if now is None else now
        expired = [r for r in self._records.values()
                   if self.policy.is_expired(r.created_at, r.data_type, current)]
        for record in expired:
            del self._records[record.id]
            self.audit.record(
                self.actor, "purge_expired", record.data_type, "allow",
                f"record={record.id} user={record.user_id}",
            )
        return len(expired)

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        """统一删除某用户数据：清理其记录 + 调用记忆系统 forget_user + 写审计。"""
        own = self.records_for(user_id)
        for record in own:
            del self._records[record.id]
        memory_counts = self.memory.forget_user(user_id)
        self.audit.record(
            self.actor, "delete_user_data", user_id, "allow",
            f"records={len(own)} memory={memory_counts}",
        )
        return {"user_id": user_id, "records": len(own), "memory": memory_counts}


__all__ = ["RetentionPolicy", "RetentionRecord", "RetentionManager"]
