"""可替换的存储后端抽象与线程安全的内存实现。

上层记忆模块只依赖 :class:`MemoryStore` 协议，因此可以把默认内存后端替换为
Redis / Postgres 等实现，而无需修改 WorkingMemory / EpisodicMemory / UserMemory。
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Iterator, Protocol, runtime_checkable

# 命名空间约定：每个用户拥有独立的情景记忆与用户记忆命名空间，
# 从存储层面保证跨用户数据隔离。
WORKING_NAMESPACE = "working"
EPISODIC_PREFIX = "episodic:"
USER_PREFIX = "user:"


def episodic_namespace(user_id: str) -> str:
    """返回某用户情景记忆的命名空间。"""
    return f"{EPISODIC_PREFIX}{user_id}"


def user_namespace(user_id: str) -> str:
    """返回某用户长期记忆的命名空间。"""
    return f"{USER_PREFIX}{user_id}"


@runtime_checkable
class MemoryStore(Protocol):
    """记忆存储协议：按 ``namespace`` + ``key`` 存取任意可序列化值。

    实现方需保证 ``get`` / ``set`` 返回与写入的值互不影响（防御性拷贝），
    并通过 :meth:`lock` 提供复合操作的临界区。
    """

    def get(self, namespace: str, key: str) -> Any | None: ...

    def set(self, namespace: str, key: str, value: Any) -> None: ...

    def delete(self, namespace: str, key: str) -> bool: ...

    def keys(self, namespace: str) -> list[str]: ...

    def delete_namespace(self, namespace: str) -> bool: ...

    def namespaces(self) -> list[str]: ...

    def clear(self) -> None: ...

    def lock(self) -> Any: ...


class InMemoryMemoryStore:
    """基于字典的线程安全存储，带防御性深拷贝。"""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def get(self, namespace: str, key: str) -> Any | None:
        """读取值，返回深拷贝以避免调用方修改内部状态。"""
        with self._lock:
            bucket = self._data.get(namespace)
            if bucket is None or key not in bucket:
                return None
            return deepcopy(bucket[key])

    def set(self, namespace: str, key: str, value: Any) -> None:
        """写入值的深拷贝。"""
        with self._lock:
            self._data.setdefault(namespace, {})[key] = deepcopy(value)

    def delete(self, namespace: str, key: str) -> bool:
        """删除一个键；键不存在时返回 ``False``。"""
        with self._lock:
            bucket = self._data.get(namespace)
            if bucket is None or key not in bucket:
                return False
            del bucket[key]
            return True

    def keys(self, namespace: str) -> list[str]:
        """列出命名空间中的键（保持插入顺序）。"""
        with self._lock:
            bucket = self._data.get(namespace)
            return list(bucket.keys()) if bucket else []

    def delete_namespace(self, namespace: str) -> bool:
        """删除整个命名空间；不存在时返回 ``False``。"""
        with self._lock:
            return self._data.pop(namespace, None) is not None

    def namespaces(self) -> list[str]:
        """列出所有命名空间。"""
        with self._lock:
            return list(self._data.keys())

    def clear(self) -> None:
        """清空所有数据。"""
        with self._lock:
            self._data.clear()

    @contextmanager
    def lock(self) -> Iterator[None]:
        """返回可重入锁的上下文管理器，用于包裹复合读写操作。"""
        with self._lock:
            yield
