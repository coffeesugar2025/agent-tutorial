"""Redis 滑动窗口限流（含本地降级）。"""

from __future__ import annotations

import logging

from app.common.errors import rate_limited
from app.config import settings
from app.infra.redis import redis_hub

logger = logging.getLogger(__name__)


def build_key(*parts: object) -> str:
    return "rl:" + ":".join(str(p) for p in parts)


def check_rate_limit(
    key: str,
    limit: int | None = None,
    window: int = 60,
    message: str = "请求过于频繁，请稍后再试",
) -> None:
    """超过阈值抛 42900；Redis 不可用时走本地窗口，语义一致。"""
    effective = limit if limit is not None else settings.rate_limit_per_minute
    if effective <= 0:
        return
    if not redis_hub.sliding_window_allow(key, effective, window):
        logger.warning("限流命中 key=%s limit=%s window=%s", key, effective, window)
        raise rate_limited(message)


def limit_chat(user_id: int, session_id: int | None = None) -> None:
    """对话接口：按用户限流（默认 30 次/分钟）。"""
    check_rate_limit(build_key("chat", user_id), message="对话太快啦，休息一下再问～")


def limit_login(username: str, ip: str | None = None) -> None:
    """登录接口：单用户名 5 次/分钟，单 IP 20 次/分钟。"""
    check_rate_limit(build_key("login", username), limit=5, window=60, message="登录尝试过于频繁")
    if ip:
        check_rate_limit(build_key("login", "ip", ip), limit=20, window=60, message="登录尝试过于频繁")


def limit_ingest(user_id: int) -> None:
    """知识库上传：10 次/分钟。"""
    check_rate_limit(build_key("ingest", user_id), limit=10, window=60, message="上传过于频繁")


def current_window_usage(key: str) -> int:
    """调试用：读取窗口内计数（Redis 不可用时返回 -1）。"""
    try:
        client = redis_hub._connect()  # noqa: SLF001 - 仅调试辅助
        if client is None:
            return -1
        return int(client.zcard(key))
    except Exception:  # noqa: BLE001
        return -1


__all__ = [
    "build_key",
    "check_rate_limit",
    "current_window_usage",
    "limit_chat",
    "limit_ingest",
    "limit_login",
]
