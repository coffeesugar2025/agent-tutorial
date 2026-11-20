import asyncio
import json

import aio_pika
from loguru import logger

from app.core.config import settings


class RabbitClient:
    """Topic 交换机 + 事件发布/消费。不可用时自动降级。"""

    def __init__(self) -> None:
        self._conn: aio_pika.RobustConnection | None = None
        self._channel: aio_pika.abc.AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None
        self.enabled = False
        self._consumer_task: asyncio.Task | None = None

    async def connect(self) -> None:
        if not settings.ENABLE_RABBITMQ:
            logger.warning("[rabbitmq] disabled by config")
            return
        try:
            self._conn = await aio_pika.connect_robust(settings.rabbitmq_url)
            self._channel = await self._conn.channel()
            self._exchange = await self._channel.declare_exchange(
                settings.RABBITMQ_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            )
            self.enabled = True
            logger.info("[rabbitmq] connected")
            self._consumer_task = asyncio.create_task(self._consume_audit())
        except Exception as exc:
            self.enabled = False
            logger.warning(f"[rabbitmq] unavailable, degraded: {exc}")

    async def publish(self, routing_key: str, payload: dict) -> None:
        if not self.enabled or not self._exchange:
            return
        message = aio_pika.Message(
            body=json.dumps(payload, ensure_ascii=False, default=str).encode(),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            content_type="application/json",
        )
        await self._exchange.publish(message, routing_key=routing_key)

    async def _consume_audit(self) -> None:
        """示例消费者：审计事件落本地日志，可替换成实际下游处理。"""
        try:
            queue = await self._channel.declare_queue("admin.audit.worker", durable=True)
            await queue.bind(self._exchange, routing_key="audit.*")

            async def handler(msg: aio_pika.abc.AbstractIncomingMessage) -> None:
                async with msg.process():
                    logger.info(f"[rabbitmq] audit event <- {msg.body.decode()}")

            await queue.consume(handler)
        except Exception as exc:
            logger.warning(f"[rabbitmq] consumer stopped: {exc}")

    async def close(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
        if self._conn:
            await self._conn.close()

    async def ping(self) -> bool:
        return bool(self.enabled and self._conn and not self._conn.is_closed)


rabbit_client = RabbitClient()
