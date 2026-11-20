import redis.asyncio as redis
from loguru import logger

from app.core.config import settings


class RedisClient:
    """Token 黑名单 / 缓存 / 验证码统一入口。连接失败自动降级为不启用。"""

    def __init__(self) -> None:
        self._client: redis.Redis | None = None
        self.enabled = False

    async def connect(self) -> None:
        if not settings.ENABLE_REDIS:
            logger.warning("[redis] disabled by config")
            return
        try:
            self._client = redis.from_url(settings.redis_url, decode_responses=True)
            await self._client.ping()
            self.enabled = True
            logger.info("[redis] connected")
        except Exception as exc:
            self.enabled = False
            logger.warning(f"[redis] unavailable, degraded: {exc}")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def ping(self) -> bool:
        try:
            return bool(self.enabled and await self._client.ping())
        except Exception:
            return False

    async def setex(self, key: str, ttl: int, value: str) -> None:
        if self.enabled:
            await self._client.setex(key, ttl, value)

    async def get(self, key: str) -> str | None:
        return await self._client.get(key) if self.enabled else None

    async def delete(self, key: str) -> None:
        if self.enabled:
            await self._client.delete(key)

    async def blacklist(self, jti: str, ttl: int) -> None:
        await self.setex(f"bl:{jti}", max(ttl, 1), "1")

    async def is_blacklisted(self, jti: str) -> bool:
        if not self.enabled:
            return False
        return bool(await self._client.exists(f"bl:{jti}"))

    async def cache_refresh(self, username: str, jti: str) -> None:
        await self.setex(f"refresh:{username}", settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400, jti)

    async def check_refresh(self, username: str, jti: str) -> bool:
        if not self.enabled:
            return True  # 无 Redis 时仅靠 JWT 自身校验
        return await self.get(f"refresh:{username}") == jti


redis_client = RedisClient()
