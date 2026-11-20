from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, require_perm
from app.db.elasticsearch import es_client
from app.schemas import ok, page_payload

router = APIRouter(prefix="/audit-logs", tags=["审计日志"])


@router.get("", summary="检索审计日志（Elasticsearch）")
async def search_logs(
    keyword: str = "",
    action: str = "",
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    _: CurrentUser = Depends(require_perm("audit:list")),
):
    if not es_client.enabled:
        return ok(page_payload([], 0, page, size), "Elasticsearch 未连接，暂无日志")
    items, total = await es_client.search(keyword, action, page, size)
    return ok(page_payload(items, total, page, size))
