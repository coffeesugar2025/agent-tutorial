"""Redis 缓存适配器：未配置 URL 或缺少驱动时回退到带 TTL 的进程内 dict。

redis 依赖只在真正需要连接时导入；status() 只检查配置与驱动可用性，
不会发起网络连接，因此本地测试完全确定性。
"""
from __future__ import annotations

import importlib.util
import json
import threading
import time
from typing import Any

from .settings import InfraSettings


class RedisCache:
    """Redis / 内存双模缓存，接口对齐常见 KV 操作。"""

    def __init__(self, url: str | None = None,
                 settings: InfraSettings | None = None) -> None:
        cfg = settings or InfraSettings.from_env()
        self.url = url if url is not None else cfg.redis_url
        self._client: Any = None
        self._local: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        """是否已显式配置 Redis URL。"""
        return bool(self.url)

    @staticmethod
    def _driver_available() -> bool:
        return importlib.util.find_spec("redis") is not None

    def _get_client(self) -> Any:
        """懒加载 Redis 客户端；不可用时返回 None 触发内存回退。"""
        if not self.configured or not self._driver_available():
            return None
        if self._client is None:
            try:
                import redis  # type: ignore

                self._client = redis.Redis.from_url(self.url, decode_responses=True)
            except Exception:  # 配置错误不应影响主流程
                return None
        return self._client

    @staticmethod
    def _encode(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)

    @staticmethod
    def _decode(raw: Any) -> Any:
        if not isinstance(raw, str):
            return raw
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    def get(self, key: str) -> Any:
        """读取键值；内存回退下自动清理过期项。"""
        client = self._get_client()
        if client is not None:
            raw = client.get(str(key))
            return self._decode(raw) if raw is not None else None
        with self._lock:
            entry = self._local.get(str(key))
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at is not None and time.monotonic() >= expires_at:
                self._local.pop(str(key), None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: int | float | None = None) -> None:
        """写入键值；ttl 单位为秒，None 表示永不过期。"""
        client = self._get_client()
        if client is not None:
            client.set(str(key), self._encode(value),
                       ex=int(ttl) if ttl and ttl > 0 else None)
            return
        expires_at = time.monotonic() + float(ttl) if ttl is not None else None
        with self._lock:
            self._local[str(key)] = (value, expires_at)

    def delete(self, key: str) -> bool:
        """删除键，返回是否存在。"""
        client = self._get_client()
        if client is not None:
            return bool(client.delete(str(key)))
        with self._lock:
            return self._local.pop(str(key), None) is not None

    def incr(self, key: str, amount: int = 1) -> int:
        """自增计数，返回自增后的值。"""
        client = self._get_client()
        if client is not None:
            return int(client.incr(str(key), amount))
        with self._lock:
            entry = self._local.get(str(key))
            current, expires_at = entry if entry else (0, None)
            if expires_at is not None and time.monotonic() >= expires_at:
                current, expires_at = 0, None
            if isinstance(current, (int, float)):
                base = int(current)
            elif isinstance(current, str) and current.lstrip("-").isdigit():
                base = int(current)
            else:
                base = 0
            value = base + amount
            self._local[str(key)] = (value, expires_at)
            return value

    def status(self) -> dict[str, Any]:
        """组件状态（不建立网络连接）。"""
        active = self._get_client() is not None
        if not self.configured:
            detail = "not_configured: ECOM_REDIS_URL 未配置，使用进程内 dict 回退（带 TTL）"
        elif not self._driver_available():
            detail = "not_configured: 缺少 redis 驱动，使用进程内 dict 回退"
        elif not active:
            detail = "Redis URL 无效，使用进程内 dict 回退"
        else:
            detail = "Redis 驱动可用，使用 Redis 后端"
        return {
            "configured": self.configured,
            "active": active,
            "backend": "redis" if active else "memory",
            "detail": detail,
        }
