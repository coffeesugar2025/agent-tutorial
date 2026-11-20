from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, require_perm
from app.crud import load_roles, user_crud, user_to_dict
from app.db.mysql import get_db
from app.models import User
from app.schemas import ResetPasswordIn, UserCreate, UserUpdate, ok, page_payload
from app.services import audit
from app.services.auth import make_password

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.get("", summary="用户列表（分页/搜索）")
async def list_users(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    keyword: str = "",
    db: AsyncSession = Depends(get_db),
    _: CurrentUser = Depends(require_perm("user:list")),
):
    items, total = await user_crud.list(
        db, page, size, keyword, ["username", "nickname", "email", "phone"]
    )
    return ok(page_payload([user_to_dict(u) for u in items], total, page, size))


@router.post("", summary="新增用户")
async def create_user(
    body: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("user:create")),
):
    if (await db.execute(select(User).where(User.username == body.username))).scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名已存在")
    values = body.model_dump(exclude={"password", "role_ids"})
    values["hashed_password"] = make_password(body.password)
    values["roles"] = await load_roles(db, body.role_ids)
    user = await user_crud.create(db, values)
    await audit.record(current.username, "create", "user", f"新增用户 {user.username}", request)
    return ok(user_to_dict(user))


@router.put("/{user_id}", summary="编辑用户")
async def update_user(
    user_id: int,
    body: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("user:update")),
):
    user = await user_crud.get(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.is_superuser and not current.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "不可编辑超级管理员")
    values = body.model_dump(exclude_none=True, exclude={"role_ids"})
    if body.role_ids is not None:
        user.roles = await load_roles(db, body.role_ids)
    await user_crud.update(db, user, values)
    await audit.record(current.username, "update", "user", f"编辑用户 {user.username}", request)
    return ok(user_to_dict(user))


@router.patch("/{user_id}/reset-password", summary="重置密码")
async def reset_password(
    user_id: int,
    body: ResetPasswordIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("user:update")),
):
    user = await user_crud.get(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    await user_crud.update(db, user, {"hashed_password": make_password(body.password)})
    await audit.record(current.username, "update", "user", f"重置 {user.username} 密码", request)
    return ok(message="密码已重置")


@router.delete("/{user_id}", summary="删除用户")
async def delete_user(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: CurrentUser = Depends(require_perm("user:delete")),
):
    user = await user_crud.get(db, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "超级管理员不可删除")
    if user.id == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")
    await user_crud.delete(db, user_id)
    await audit.record(current.username, "delete", "user", f"删除用户 {user.username}", request)
    return ok(message="已删除")
