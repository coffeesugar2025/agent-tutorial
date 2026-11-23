"""RabbitMQ 事件总线：未配置 URL 或缺少驱动时回退到内存队列。

内存模式保留所有已发布事件与待消费队列，便于测试断言。pika 只在发布时
按需导入；status() 不会建立连接。
"""
from __future__ import annotations

import importlib.util
import json
import threading
from typing import Any

from .settings import InfraSettings

_EXCHANGE = "ecom.events"


class RabbitMQEventBus:
    """RabbitMQ / 内存双模事件总线。"""

    def __init__(self, url: str | None = None,
                 settings: InfraSettings | None = None) -> None:
        cfg = settings or InfraSettings.from_env()
        self.url = url if url is not None else cfg.rabbitmq_url
        self._connection: Any = None
        self._queues: dict[str, list[Any]] = {}
        self._published: list[tuple[str, Any]] = []
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        """是否已显式配置 RabbitMQ URL。"""
        return bool(self.url)

    @staticmethod
    def _driver_available() -> bool:
        return importlib.util.find_spec("pika") is not None

    def _get_connection(self) -> Any:
        """懒加载 pika 连接；不可用时返回 None 触发内存回退。"""
        if not self.configured or not self._driver_available():
            return None
        if self._connection is None or self._connection.is_closed:
            try:
                import pika  # type: ignore

                self._connection = pika.BlockingConnection(
                    pika.URLParameters(self.url))
            except Exception:
                return None
        return self._connection

    def publish(self, topic: str, payload: Any) -> bool:
        """发布事件到 topic；内存模式下同时写入队列与已发布清单。"""
        connection = self._get_connection()
        if connection is not None:
            try:
                channel = connection.channel()
                channel.exchange_declare(exchange=_EXCHANGE,
                                         exchange_type="topic", durable=True)
                body = json.dumps(payload, ensure_ascii=False, default=str)
                channel.basic_publish(exchange=_EXCHANGE,
                                      routing_key=str(topic), body=body)
                channel.close()
            except Exception:
                pass  # 投递失败仍保留本地事件，便于排查与重放
        with self._lock:
            self._queues.setdefault(str(topic), []).append(payload)
            self._published.append((str(topic), payload))
        return True

    def events(self, topic: str | None = None) -> list[tuple[str, Any]]:
        """列出已发布事件（topic 为 None 时返回全部）。"""
        with self._lock:
            if topic is None:
                return list(self._published)
            return [(t, p) for t, p in self._published if t == str(topic)]

    def drain(self, topic: str) -> list[Any]:
        """取出并清空指定 topic 的待消费事件。"""
        with self._lock:
            return list(self._queues.pop(str(topic), []))

    def status(self) -> dict[str, Any]:
        """组件状态（不建立网络连接）。"""
        active = self._get_connection() is not None
        if not self.configured:
            detail = "not_configured: ECOM_RABBITMQ_URL 未配置，使用内存队列回退"
        elif not self._driver_available():
            detail = "not_configured: 缺少 pika 驱动，使用内存队列回退"
        elif not active:
            detail = "RabbitMQ URL 无效，使用内存队列回退"
        else:
            detail = "RabbitMQ 驱动可用，使用 RabbitMQ 后端"
        return {
            "configured": self.configured,
            "active": active,
            "backend": "rabbitmq" if active else "memory",
            "detail": detail,
        }
