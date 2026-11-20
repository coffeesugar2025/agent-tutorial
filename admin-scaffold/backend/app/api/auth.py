from fastapi import APIRouter, Depends, HTTPException, Request, status
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, get_current_user
from app.core.security import decode_token
from app.db.mysql import get_db
from app.db.redis import redis_client
from app.schemas import LoginIn, MenuOut, ProfileOut, RefreshIn, TokenOut, ok
from app.services import audit
from app.services.auth import authenticate, issue_tokens, revoke_access

router = APIRouter(prefix="/auth", tags=["认证"])

MENUS = [
    MenuOut(path="/dashboard", title="工作台", icon="DataBoard", perm="dashboard:view"),
    MenuOut(path="/system/user", title="用户管理", icon="User", perm="user:list"),
    MenuOut(path="/system/role", title="角色管理", icon="UserFilled", perm="role:list"),
    MenuOut(path="/system/permission", title="权限管理", icon="Lock", perm="permission:list"),
    MenuOut(path="/system/audit", title="审计日志", icon="Document", perm="audit:list"),
]


@router.post("/login", summary="登录")
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_db)):
    user = await authenticate(db, body.username, body.password)
    token = await issue_tokens(user)
    await audit.record(user.username, "login", "auth", f"{user.username} 登录成功", request)
    return ok(token.model_dump())


@router.post("/refresh", summary="刷新 access token")
async def refresh(body: RefreshIn, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token)
    except (ExpiredSignatureError, InvalidTokenError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token 无效或已过期")
    if payload.get("type") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token 类型错误")
    from sqlalchemy import select

    from app.models import User

    user = (await db.execute(select(User).where(User.id == int(payload["sub"])))).scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不可用")
    if not await redis_client.check_refresh(user.username, payload.get("jti", "")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "refresh token 已失效")
    return ok((await issue_tokens(user)).model_dump())


@router.post("/logout", summary="退出登录（拉黑当前 token）")
async def logout(request: Request, user: CurrentUser = Depends(get_current_user)):
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    try:
        payload = decode_token(token)
        await revoke_access(token, payload)
    except Exception:
        pass
    await redis_client.delete(f"refresh:{user.username}")
    await audit.record(user.username, "logout", "auth", "退出登录", request)
    return ok(message="已退出")


@router.get("/me", summary="当前用户信息与权限")
async def me(user: CurrentUser = Depends(get_current_user)):
    return ok(
        ProfileOut(
            id=user.id,
            username=user.username,
            nickname=user.nickname,
            is_superuser=user.is_superuser,
            roles=user.roles,
            permissions=sorted(user.permissions),
        ).model_dump()
    )


@router.get("/menus", summary="按权限返回菜单")
async def menus(user: CurrentUser = Depends(get_current_user)):
    return ok([m.model_dump() for m in MENUS if user.has(m.perm)])
