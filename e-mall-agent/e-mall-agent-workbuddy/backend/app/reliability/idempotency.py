"""幂等保护。

提供可替换存储的幂等键守卫：同一个 key 的并发或重复调用只会真正执行一次，
结果按 TTL 缓存。默认使用线程安全的内存存储，可通过实现
``IdempotencyStore`` 协议替换为 Redis 等分布式存储。
"""
from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class IdempotencyStore(Protocol):
    """幂等结果存储接口，可替换为 Redis 实现。

    ``get`` 返回 ``(hit, value)``，``hit`` 为 False 表示未命中或已过期。
    方法可以是同步的，也可以是异步的（守卫会自动 await）。
    """

    def get(self, key: str) -> tuple[bool, Any]: ...

    def set(self, key: str, value: Any, ttl: float) -> None: ...

    def delete(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """默认内存存储：基于单调时钟的 TTL 缓存，加锁保证并发安全。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> tuple[bool, Any]:
        """读取缓存；过期条目会被惰性删除并视为未命中。"""
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return False, None
            expires_at, value = item
            if time.monotonic() >= expires_at:
                del self._data[key]
                return False, None
            return True, value

    async def set(self, key: str, value: Any, ttl: float) -> None:
        """写入缓存，``ttl`` 为有效秒数。"""
        async with self._lock:
            self._data[key] = (time.monotonic() + ttl, value)

    async def delete(self, key: str) -> None:
        """删除指定键的缓存。"""
        async with self._lock:
            self._data.pop(key, None)


class IdempotencyGuard:
    """幂等执行守卫。

    同一个 key 在缓存有效期内只会执行一次 ``fn``。并发调用时，除首个
    "领头" 调用外，其余调用会等待同一个 future 并共享结果；异常同样
    会被共享，且不会写入缓存，便于后续重试。

    Args:
        store: 结果存储，默认 ``InMemoryIdempotencyStore``。
        default_ttl: 默认缓存有效期秒数。
    """

    def __init__(
        self,
        store: IdempotencyStore | None = None,
        default_ttl: float = 60.0,
    ) -> None:
        self.store = store or InMemoryIdempotencyStore()
        self.default_ttl = default_ttl
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """若 value 是 awaitable 则等待并返回其结果，否则原样返回。"""
        if inspect.isawaitable(value):
            return await value
        return value

    async def execute(
        self,
        key: str,
        fn: Callable[[], T | Awaitable[T]],
        *,
        ttl: float | None = None,
    ) -> T:
        """以 key 为幂等标识执行 ``fn``。

        Args:
            key: 幂等键。
            fn: 无参可调用对象，同步/异步均可。
            ttl: 本次结果缓存时间；None 时使用 ``default_ttl``。

        Returns:
            首次执行的结果或缓存中的结果。
        """
        hit, cached = await self._maybe_await(self.store.get(key))
        if hit:
            return cached

        async with self._lock:
            hit, cached = await self._maybe_await(self.store.get(key))
            if hit:
                return cached
            future = self._inflight.get(key)
            leader = future is None
            if leader:
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future

        if not leader:
            return await future  # type: ignore[misc]

        try:
            result = await self._maybe_await(fn())
            await self._maybe_await(
                self.store.set(key, result, self.default_ttl if ttl is None else ttl)
            )
            future.set_result(result)  # type: ignore[union-attr]
            return result
        except BaseException as exc:
            future.set_exception(exc)  # type: ignore[union-attr]
            # 无并发跟随者时主动标记已检索，避免 "Future exception was never retrieved" 警告；
            # 这不会清除异常，跟随者 await 该 future 仍会得到同一个异常。
            future.exception()  # type: ignore[union-attr]
            raise
        finally:
            async with self._lock:
                self._inflight.pop(key, None)
