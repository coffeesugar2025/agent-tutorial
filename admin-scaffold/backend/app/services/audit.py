import asyncio

from fastapi import Request
from loguru import logger

from app.core.config import settings
from app.db.elasticsearch import es_client
from app.mq.kafka import kafka_client
from app.mq.rabbitmq import rabbit_client
from app.schemas import AuditEvent


def client_ip(request: Request | None) -> str:
    if not request:
        return ""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


async def _safe(coro, name: str) -> None:
    try:
        await coro
    except Exception as exc:
        logger.warning(f"[audit] {name} failed, skipped: {exc}")


async def record(
    username: str,
    action: str,
    resource: str,
    detail: str = "",
    request: Request | None = None,
    blocking: bool = False,
) -> None:
    """一次写操作 → ES（检索）+ RabbitMQ（事件）+ Kafka（流），任一不可用不影响主流程。"""
    event = AuditEvent(
        username=username,
        action=action,
        resource=resource,
        detail=detail,
        ip=client_ip(request),
    )
    doc = event.model_dump()
    tasks = []
    if settings.ENABLE_ES and es_client.enabled:
        tasks.append(("es", es_client.index_doc(doc)))
    if settings.ENABLE_RABBITMQ and rabbit_client.enabled:
        tasks.append(("rabbitmq", rabbit_client.publish(f"audit.{action}", doc)))
    if settings.ENABLE_KAFKA and kafka_client.enabled:
        tasks.append(("kafka", kafka_client.send(doc, key=username)))

    if not tasks:
        return
    jobs = [_safe(coro, name) for name, coro in tasks]
    if blocking:
        await asyncio.gather(*jobs)
    else:
        for job in jobs:
            asyncio.create_task(job)
