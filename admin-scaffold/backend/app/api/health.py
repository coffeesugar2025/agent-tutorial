from fastapi import APIRouter

from app.db.elasticsearch import es_client
from app.db.mysql import engine
from app.db.redis import redis_client
from app.mq.kafka import kafka_client
from app.mq.rabbitmq import rabbit_client
from app.schemas import ok
from sqlalchemy import text

router = APIRouter(tags=["运维"])


@router.get("/health", summary="各中间件连通性")
async def health():
    mysql_ok = False
    try:
        from sqlalchemy.ext.asyncio import AsyncSession

        async with AsyncSession(engine) as s:
            await s.execute(text("SELECT 1"))
        mysql_ok = True
    except Exception:
        pass
    return ok(
        {
            "mysql": mysql_ok,
            "redis": await redis_client.ping(),
            "rabbitmq": await rabbit_client.ping(),
            "kafka": await kafka_client.ping(),
            "elasticsearch": await es_client.ping(),
        }
    )
