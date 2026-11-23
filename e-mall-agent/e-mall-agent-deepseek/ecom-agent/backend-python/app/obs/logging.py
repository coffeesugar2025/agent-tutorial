"""结构化日志：单行 JSON，自动注入 trace_id / session_id / user_id。"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from app.common.timeutil import iso_now
from app.common.tracecontext import get_session_id, get_span_id, get_trace_id, get_user_id

_EXTRA_FIELDS = (
    "event",
    "agentType",
    "tool",
    "model",
    "provider",
    "latencyMs",
    "costCents",
    "tokens",
    "reason",
    "status",
    "path",
    "sessionId",
)


class JsonFormatter(logging.Formatter):
    """把日志记录序列化为单行 JSON（便于 Loki/ELK 采集）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": iso_now(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "traceId": get_trace_id() or None,
            "spanId": get_span_id() or None,
            "sessionId": get_session_id(),
            "userId": get_user_id(),
        }
        for key in _EXTRA_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        extra = getattr(record, "context", None)
        if isinstance(extra, dict):
            payload.update(extra)
        return json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False, default=str)


def setup_logging(level: str | None = None) -> None:
    """初始化根日志器（幂等，可重复调用）。"""
    root = logging.getLogger()
    if getattr(root, "_ecom_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    root.setLevel((level or "INFO").upper())
    # 降低三方库噪音
    for noisy in ("pika", "urllib3", "httpx", "httpcore", "pymilvus"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._ecom_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, message: str, **fields: Any) -> None:
    """带业务事件的日志（event 字段便于日志检索与告警）。"""
    logger.info(message, extra={"event": event, **fields})


__all__ = ["JsonFormatter", "get_logger", "log_event", "setup_logging"]
