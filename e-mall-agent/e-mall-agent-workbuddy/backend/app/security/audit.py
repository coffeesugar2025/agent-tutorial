"""Append-only in-memory audit log for permission decisions and side effects."""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from ..config import get_settings


class AuditLogger:
    def __init__(self, max_entries: int | None = None) -> None:
        self._max = max_entries or get_settings().audit_max_entries
        self._entries: deque[dict[str, Any]] = deque(maxlen=self._max)
        self._lock = threading.Lock()

    def record(self, actor: str, action: str, resource: str,
               decision: str = "allow", detail: str = "") -> dict[str, Any]:
        entry = {"ts": time.time(), "actor": actor, "action": action,
                 "resource": resource, "decision": decision, "detail": detail}
        with self._lock:
            self._entries.append(entry)
        return entry

    def query(self, limit: int = 50, actor: str | None = None,
              decision: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._entries)
        if actor:
            items = [e for e in items if e["actor"] == actor]
        if decision:
            items = [e for e in items if e["decision"] == decision]
        return list(reversed(items))[:limit]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_audit: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _audit
    if _audit is None:
        _audit = AuditLogger()
    return _audit
