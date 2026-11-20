from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_perm
from app.crud import permission_crud
from app.db.mysql import get_db
from app.models import Permission
from app.schemas import PermissionCreate, PermissionUpdate, ok, page_payload

router = APIRouter(prefix="/permissions", tags=["权限管理"])


def _out(p: Permission) -> dict:
    return {
        "id": p.id,
        "code": p.code,
        "name": p.name,
        "module": p.module,
        "kind": p.kind,
        "sort": p.sort,
        "created_at": p.created_at,
    }


@router.get("", summary="权限列表")
async def list_permissions(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: str = "",
    module: str = "",
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_perm("permission:list")),
):
    where = []
    if module:
        where.append(Permission.module == module)
    items, total = await permission_crud.list(
        db, page, size, keyword, ["code", "name"], extra_where=where
    )
    return ok(page_payload([_out(p) for p in items], total, page, size))


@router.get("/tree", summary="按模块分组（角色分配权限用）")
async def permission_tree(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    items, _ = await permission_crud.list(db, 1, 500)
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in items:
        groups[p.module].append({"id": p.id, "code": p.code, "name": p.name, "kind": p.kind})
    return ok([{"module": k, "children": v} for k, v in sorted(groups.items())])


@router.post("", summary="新增权限")
async def create_permission(
    body: PermissionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("permission:create")),
):
    if (await db.execute(select(Permission).where(Permission.code == body.code))).scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "权限编码已存在")
    p = await permission_crud.create(db, body.model_dump())
    from app.services import audit

    await audit.record(current.username, "create", "permission", f"新增权限 {p.code}", request)
    return ok(_out(p))


@router.put("/{perm_id}", summary="编辑权限")
async def update_permission(
    perm_id: int,
    body: PermissionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("permission:update")),
):
    p = await permission_crud.get(db, perm_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "权限不存在")
    await permission_crud.update(db, p, body.model_dump(exclude_none=True))
    from app.services import audit

    await audit.record(current.username, "update", "permission", f"编辑权限 {p.code}", request)
    return ok(_out(p))


@router.delete("/{perm_id}", summary="删除权限")
async def delete_permission(
    perm_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("permission:delete")),
):
    p = await permission_crud.get(db, perm_id)
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "权限不存在")
    code = p.code
    await permission_crud.delete(db, perm_id)
    from app.services import audit

    await audit.record(current.username, "delete", "permission", f"删除权限 {code}", request)
    return ok(message="已删除")
