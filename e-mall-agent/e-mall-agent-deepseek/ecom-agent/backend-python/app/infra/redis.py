"""Redis 封装：缓存、限流、分布式锁、熔断状态。

设计原则（对应"任何降级都要打日志与指标"）：
* 懒连接 + 冷却期：Redis 不可用时 30s 内不再重试，避免每请求都卡连接超时；
* 全部方法都有本地内存降级路径，接口语义保持一致（跨进程失效可接受）；
* 降级只记一次告警指标，不抛异常打断主流程。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-14] 可靠性/降级
# 职责：Redis 封装：缓存、限流、分布式锁、熔断状态
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from typing import Any

from app.config import settings
from app.obs.metrics import record_degradation

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 取决于运行环境
    from redis import Redis
    from redis.exceptions import RedisError

    REDIS_AVAILABLE = True
except Exception:  # noqa: BLE001
    Redis = None  # type: ignore[assignment]
    RedisError = Exception  # type: ignore[assignment,misc]
    REDIS_AVAILABLE = False

_COOLDOWN_SECONDS = 30.0


class LocalFallback:
    """进程内 KV / 滑动窗口 / 锁，用于 Redis 不可用时兜底。"""

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, float]] = {}
        self._windows: dict[str, list[float]] = {}
        self._locks: dict[str, tuple[str, float]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> str | None:
        with self._lock:
            item = self._values.get(key)
            if not item:
                return None
            value, expire_at = item
            if expire_at and expire_at < time.time():
                self._values.pop(key, None)
                return None
            return value

    def set(self, key: str, value: str, ttl: int | None) -> None:
        with self._lock:
            expire_at = time.time() + ttl if ttl else 0.0
            self._values[key] = (value, expire_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)

    def window_allow(self, key: str, limit: int, window: int) -> bool:
        now = time.time()
        with self._lock:
            stamps = [t for t in self._windows.get(key, []) if now - t < window]
            allowed = len(stamps) < limit
            if allowed:
                stamps.append(now)
            self._windows[key] = stamps
            return allowed

    def acquire(self, key: str, ttl: int) -> str | None:
        token = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            current = self._locks.get(key)
            if current and current[1] > now:
                return None
            self._locks[key] = (token, now + ttl)
        return token

    def release(self, key: str, token: str) -> bool:
        with self._lock:
            current = self._locks.get(key)
            if current and current[0] == token:
                self._locks.pop(key, None)
                return True
            return False

    def clear(self) -> None:
        with self._lock:
            self._values.clear()
            self._windows.clear()
            self._locks.clear()


class RedisHub:
    """Redis 门面：内部自动处理不可用降级。"""

    def __init__(self) -> None:
        self._client: Any = None
        self._local = LocalFallback()
        self._degraded_until = 0.0
        self._lock = threading.Lock()
        self._degraded_warned = False

    # --- 连接管理 -----------------------------------------------------------
    def _mark_degraded(self, reason: str) -> None:
        self._degraded_until = time.time() + _COOLDOWN_SECONDS
        if not self._degraded_warned:
            self._degraded_warned = True
            record_degradation("redis", reason)
        self._client = None

    def _connect(self) -> Any:
        if not REDIS_AVAILABLE or not settings.redis_configured:
            return None
        if time.time() < self._degraded_until:
            return None
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                client = Redis(
                    host=settings.redis_host,
                    port=settings.redis_port,
                    password=settings.redis_password or None,
                    db=settings.redis_db,
                    socket_timeout=settings.redis_socket_timeout,
                    socket_connect_timeout=settings.redis_connect_timeout,
                    decode_responses=True,
                    health_check_interval=30,
                )
                client.ping()
                self._client = client
                self._degraded_warned = False
                logger.info("Redis 已连接 %s:%s/%s", settings.redis_host, settings.redis_port, settings.redis_db)
                return client
            except Exception as exc:  # noqa: BLE001
                self._mark_degraded(f"connect:{type(exc).__name__}")
                return None

    def available(self) -> bool:
        return self._connect() is not None

    def _run(self, operation: str, func: Any, fallback: Any) -> Any:
        client = self._connect()
        if client is None:
            return fallback()
        try:
            return func(client)
        except Exception as exc:  # noqa: BLE001
            self._mark_degraded(f"{operation}:{type(exc).__name__}")
            return fallback()

    # --- 缓存 ---------------------------------------------------------------
    def get_json(self, key: str) -> Any:
        def _fallback() -> Any:
            raw = self._local.get(key)
            return json.loads(raw) if raw else None

        def _op(client: Any) -> Any:
            raw = client.get(key)
            return json.loads(raw) if raw else None

        return self._run("get", _op, _fallback)

    def set_json(self, key: str, value: Any, ttl: int | None = 300) -> None:
        payload = json.dumps(value, ensure_ascii=False, default=str)
        self._run(
            "set",
            lambda client: client.set(key, payload, ex=ttl) if ttl else client.set(key, payload),
            lambda: self._local.set(key, payload, ttl),
        )

    def delete(self, key: str) -> None:
        self._run("delete", lambda client: client.delete(key), lambda: self._local.delete(key))

    def incr(self, key: str, ttl: int | None = 60) -> int:
        def _fallback() -> int:
            raw = self._local.get(key)
            value = int(raw or 0) + 1
            self._local.set(key, str(value), ttl)
            return value

        def _op(client: Any) -> int:
            value = client.incr(key)
            if value == 1 and ttl:
                client.expire(key, ttl)
            return int(value)

        return self._run("incr", _op, _fallback)

    # --- 限流 ---------------------------------------------------------------
    def sliding_window_allow(self, key: str, limit: int, window: int = 60) -> bool:
        """滑动窗口限流：Redis ZSET 记录时间戳，本地 deque 兜底。"""

        def _fallback() -> bool:
            return self._local.window_allow(key, limit, window)

        def _op(client: Any) -> bool:
            now = time.time()
            member = f"{now:.6f}:{uuid.uuid4().hex[:8]}"
            pipe = client.pipeline()
            pipe.zremrangebyscore(key, 0, now - window)
            pipe.zadd(key, {member: now})
            pipe.zcard(key)
            pipe.expire(key, window + 1)
            results = pipe.execute()
            count = int(results[2])
            return count <= limit

        return bool(self._run("ratelimit", _op, _fallback))

    # --- 分布式锁 -----------------------------------------------------------
    def acquire_lock(self, name: str, ttl: int = 30) -> str | None:
        key = f"lock:{name}"
        token = uuid.uuid4().hex

        def _op(client: Any) -> str | None:
            return token if client.set(key, token, nx=True, ex=ttl) else None

        return self._run("lock", _op, lambda: self._local.acquire(key, ttl))

    def release_lock(self, name: str, token: str) -> bool:
        key = f"lock:{name}"

        def _op(client: Any) -> bool:
            current = client.get(key)
            if current == token:
                client.delete(key)
                return True
            return False

        return bool(self._run("unlock", _op, lambda: self._local.release(key, token)))

    # --- 熔断状态（跨进程共享） --------------------------------------------
    def set_state(self, namespace: str, key: str, value: Any, ttl: int = 120) -> None:
        self.set_json(f"state:{namespace}:{key}", value, ttl)

    def get_state(self, namespace: str, key: str) -> Any:
        return self.get_json(f"state:{namespace}:{key}")

    # --- 运维 ---------------------------------------------------------------
    def health(self) -> str:
        return "UP" if self.available() else "DOWN"

    def reset(self) -> None:
        """测试用：清空连接与本地降级数据。"""
        self._client = None
        self._degraded_until = 0.0
        self._degraded_warned = False
        self._local.clear()

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None


redis_hub = RedisHub()

__all__ = ["LocalFallback", "REDIS_AVAILABLE", "RedisHub", "redis_hub"]
