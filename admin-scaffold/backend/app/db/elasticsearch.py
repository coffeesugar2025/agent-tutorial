from typing import Any

from elasticsearch import AsyncElasticsearch
from loguru import logger

from app.core.config import settings


class ESClient:
    """审计日志检索。不可用时自动降级，业务写操作不被阻断。"""

    def __init__(self) -> None:
        self._client: AsyncElasticsearch | None = None
        self.enabled = False

    async def connect(self) -> None:
        if not settings.ENABLE_ES:
            logger.warning("[es] disabled by config")
            return
        try:
            kwargs: dict[str, Any] = {"hosts": settings.es_hosts}
            if settings.es_auth:
                kwargs["basic_auth"] = settings.es_auth
            self._client = AsyncElasticsearch(**kwargs)
            await self._client.info()
            await self._ensure_index()
            self.enabled = True
            logger.info("[es] connected")
        except Exception as exc:
            self.enabled = False
            logger.warning(f"[es] unavailable, degraded: {exc}")

    async def _ensure_index(self) -> None:
        if not await self._client.indices.exists(index=settings.ES_INDEX):
            await self._client.indices.create(
                index=settings.ES_INDEX,
                mappings={
                    "properties": {
                        "ts": {"type": "date"},
                        "username": {"type": "keyword"},
                        "action": {"type": "keyword"},
                        "resource": {"type": "keyword"},
                        "detail": {"type": "text"},
                        "ip": {"type": "keyword"},
                    }
                },
            )

    async def close(self) -> None:
        if self._client:
            await self._client.close()

    async def ping(self) -> bool:
        try:
            return bool(self.enabled and await self._client.ping())
        except Exception:
            return False

    async def index_doc(self, doc: dict) -> None:
        if self.enabled:
            await self._client.index(index=settings.ES_INDEX, document=doc)

    async def search(
        self, keyword: str = "", action: str = "", page: int = 1, size: int = 20
    ) -> tuple[list[dict], int]:
        if not self.enabled:
            return [], 0
        must: list[dict] = []
        if keyword:
            must.append(
                {
                    "multi_match": {
                        "query": keyword,
                        "fields": ["detail", "username", "resource"],
                    }
                }
            )
        if action:
            must.append({"term": {"action": action}})
        resp = await self._client.search(
            index=settings.ES_INDEX,
            query={"bool": {"must": must}} if must else {"match_all": {}},
            sort=[{"ts": {"order": "desc"}}],
            from_=(page - 1) * size,
            size=size,
        )
        total = resp["hits"]["total"]["value"]
        items = [hit["_source"] for hit in resp["hits"]["hits"]]
        return items, total


es_client = ESClient()
