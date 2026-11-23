"""Checkpoint model and pluggable store for long-running task recovery."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


def compute_state_hash(state: dict) -> str:
    """Stable SHA-256 of a JSON-serialisable state snapshot."""
    payload = json.dumps(state, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class TaskCheckpoint:
    """One durable snapshot taken after a step completes."""

    task_id: str
    step_index: int
    state: dict
    ts: float = field(default_factory=time.time)
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.hash:
            self.hash = compute_state_hash(self.state)

    @property
    def valid(self) -> bool:
        return self.hash == compute_state_hash(self.state)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "step_index": self.step_index,
            "state": self.state,
            "ts": self.ts,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskCheckpoint":
        return cls(
            task_id=data["task_id"],
            step_index=int(data["step_index"]),
            state=dict(data.get("state") or {}),
            ts=float(data.get("ts", time.time())),
            hash=data.get("hash", ""),
        )


@runtime_checkable
class CheckpointStore(Protocol):
    """Replaceable persistence contract (memory today, Redis/S3 tomorrow)."""

    def save(self, checkpoint: TaskCheckpoint) -> None: ...

    def load(self, task_id: str, step_index: int | None = None) -> TaskCheckpoint | None: ...

    def list(self, task_id: str | None = None) -> list[TaskCheckpoint]: ...

    def delete(self, task_id: str) -> None: ...


class InMemoryCheckpointStore:
    """Thread-safe in-memory :class:`CheckpointStore` implementation."""

    def __init__(self) -> None:
        self._data: dict[str, list[TaskCheckpoint]] = {}
        self._lock = threading.Lock()

    def save(self, checkpoint: TaskCheckpoint) -> None:
        with self._lock:
            steps = self._data.setdefault(checkpoint.task_id, [])
            for idx, existing in enumerate(steps):
                if existing.step_index == checkpoint.step_index:
                    steps[idx] = checkpoint
                    return
            steps.append(checkpoint)

    def load(self, task_id: str,
             step_index: int | None = None) -> TaskCheckpoint | None:
        with self._lock:
            steps = list(self._data.get(task_id, []))
        if not steps:
            return None
        if step_index is not None:
            for cp in steps:
                if cp.step_index == step_index:
                    return cp
            return None
        return max(steps, key=lambda cp: cp.step_index)

    def list(self, task_id: str | None = None) -> list[TaskCheckpoint]:
        with self._lock:
            if task_id is not None:
                return sorted(self._data.get(task_id, []),
                              key=lambda cp: cp.step_index)
            all_cps = [cp for group in self._data.values() for cp in group]
        return sorted(all_cps, key=lambda cp: (cp.task_id, cp.step_index))

    def delete(self, task_id: str) -> None:
        with self._lock:
            self._data.pop(task_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


__all__ = [
    "TaskCheckpoint", "CheckpointStore", "InMemoryCheckpointStore",
    "compute_state_hash",
]
