import asyncio
import json

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from loguru import logger

from app.core.config import settings


class KafkaClient:
    """审计事件流生产者 + 示例消费者。不可用时自动降级。"""

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._consumer: AIOKafkaConsumer | None = None
        self.enabled = False
        self._consumer_task: asyncio.Task | None = None

    async def connect(self) -> None:
        if not settings.ENABLE_KAFKA:
            logger.warning("[kafka] disabled by config")
            return
        try:
            self._producer = AIOKafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v, ensure_ascii=False, default=str).encode(),
            )
            await self._producer.start()
            self.enabled = True
            logger.info("[kafka] connected")
            self._consumer_task = asyncio.create_task(self._consume())
        except Exception as exc:
            self.enabled = False
            self._producer = None
            logger.warning(f"[kafka] unavailable, degraded: {exc}")

    async def send(self, payload: dict, key: str | None = None) -> None:
        if not self.enabled or not self._producer:
            return
        await self._producer.send_and_wait(
            settings.KAFKA_TOPIC, value=payload, key=key.encode() if key else None
        )

    async def _consume(self) -> None:
        try:
            self._consumer = AIOKafkaConsumer(
                settings.KAFKA_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="admin-scaffold-audit",
                auto_offset_reset="latest",
            )
            await self._consumer.start()
            async for msg in self._consumer:
                logger.info(f"[kafka] audit event <- {msg.value.decode()}")
        except Exception as exc:
            logger.warning(f"[kafka] consumer stopped: {exc}")

    async def close(self) -> None:
        if self._consumer_task:
            self._consumer_task.cancel()
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()

    async def ping(self) -> bool:
        return self.enabled


kafka_client = KafkaClient()
