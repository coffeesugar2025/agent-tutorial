"""背压：有界队列 + 超时丢弃。

队列满时 ``put`` 最多等待 ``timeout`` 秒，超时返回 False（丢弃）而非无限阻塞；
``get`` 同理返回 None。时钟与等待函数可注入以保证离线测试确定性。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable


class BoundedQueue:
    """固定容量的异步队列，提供超时语义的 put / get。"""

    def __init__(
        self,
        maxsize: int,
        *,
        clock: Callable[[], float] | None = None,
        sleeper: Callable[[float], object] | None = None,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize 必须 >= 1")
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._clock = clock or time.monotonic
        self._sleeper = sleeper or asyncio.sleep

    def __len__(self) -> int:
        return self._queue.qsize()

    @property
    def qsize(self) -> int:
        return self._queue.qsize()

    @property
    def full(self) -> bool:
        return self._queue.full()

    @property
    def empty(self) -> bool:
        return self._queue.empty()

    def put_nowait(self, item: Any) -> bool:
        """非阻塞入队；队列满返回 False。"""
        if self._queue.full():
            return False
        self._queue.put_nowait(item)
        return True

    def get_nowait(self) -> Any | None:
        """非阻塞出队；队列空返回 None。"""
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def put(self, item: Any, timeout: float | None = None) -> bool:
        """等待空位并入队；超时仍无空位则丢弃该元素返回 False。"""
        if self.put_nowait(item):
            return True
        deadline = None if timeout is None else self._clock() + timeout
        while self._queue.full():
            now = self._clock()
            if deadline is not None and now >= deadline:
                return False
            wait = 0.005 if deadline is None else min(0.005, max(0.0, deadline - now))
            await self._sleeper(wait)
        return self.put_nowait(item)

    async def get(self, timeout: float | None = None) -> Any | None:
        """等待元素出队；超时返回 None。"""
        item = self.get_nowait()
        if item is not None:
            return item
        deadline = None if timeout is None else self._clock() + timeout
        while self._queue.empty():
            now = self._clock()
            if deadline is not None and now >= deadline:
                return None
            wait = 0.005 if deadline is None else min(0.005, max(0.0, deadline - now))
            await self._sleeper(wait)
        return self.get_nowait()


__all__ = ["BoundedQueue"]
