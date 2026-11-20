from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user, require_perm
from app.crud import load_permissions, role_crud, role_to_dict
from app.db.mysql import get_db
from app.models import Role
from app.schemas import PermAssignIn, RoleCreate, RoleUpdate, ok, page_payload
from app.services import audit

router = APIRouter(prefix="/roles", tags=["角色管理"])


@router.get("", summary="角色列表")
async def list_roles(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: str = "",
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_perm("role:list")),
):
    items, total = await role_crud.list(db, page, size, keyword, ["code", "name"])
    return ok(page_payload([role_to_dict(r) for r in items], total, page, size))


@router.get("/options", summary="角色下拉选项")
async def role_options(
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(get_current_user),
):
    items, _ = await role_crud.list(db, 1, 200)
    return ok([{"id": r.id, "code": r.code, "name": r.name} for r in items])


@router.post("", summary="新增角色")
async def create_role(
    body: RoleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("role:create")),
):
    if (await db.execute(select(Role).where(Role.code == body.code))).scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "角色编码已存在")
    values = body.model_dump(exclude={"permission_ids"})
    values["permissions"] = await load_permissions(db, body.permission_ids)
    role = await role_crud.create(db, values)
    await audit.record(current.username, "create", "role", f"新增角色 {role.code}", request)
    return ok(role_to_dict(role))


@router.put("/{role_id}", summary="编辑角色")
async def update_role(
    role_id: int,
    body: RoleUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("role:update")),
):
    role = await role_crud.get(db, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "角色不存在")
    values = body.model_dump(exclude_none=True, exclude={"permission_ids"})
    if body.permission_ids is not None:
        role.permissions = await load_permissions(db, body.permission_ids)
    await role_crud.update(db, role, values)
    await audit.record(current.username, "update", "role", f"编辑角色 {role.code}", request)
    return ok(role_to_dict(role))


@router.put("/{role_id}/permissions", summary="分配权限")
async def assign_permissions(
    role_id: int,
    body: PermAssignIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("role:update")),
):
    role = await role_crud.get(db, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "角色不存在")
    role.permissions = await load_permissions(db, body.permission_ids)
    await db.flush()
    await audit.record(
        current.username, "update", "role", f"为角色 {role.code} 分配 {len(role.permissions)} 项权限", request
    )
    return ok(role_to_dict(role))


@router.delete("/{role_id}", summary="删除角色")
async def delete_role(
    role_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("role:delete")),
):
    role = await role_crud.get(db, role_id)
    if not role:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "角色不存在")
    if role.code == "super_admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "内置超级管理员角色不可删除")
    await role_crud.delete(db, role_id)
    await audit.record(current.username, "delete", "role", f"删除角色 {role.code}", request)
    return ok(message="已删除")
