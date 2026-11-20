from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.db.redis import redis_client
from app.models import Role, User
from app.schemas import TokenOut


async def authenticate(db: AsyncSession, username: str, password: str) -> User:
    result = await db.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.username == username)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已被禁用")
    return user


async def issue_tokens(user: User) -> TokenOut:
    access, _ = create_access_token(str(user.id), {"username": user.username})
    refresh, jti = create_refresh_token(str(user.id))
    await redis_client.cache_refresh(user.username, jti)
    return TokenOut(
        access_token=access,
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def revoke_access(token: str, payload: dict) -> None:
    from app.core.security import access_token_ttl

    await redis_client.blacklist(payload.get("jti", ""), access_token_ttl())


def make_password(plain: str) -> str:
    return hash_password(plain)
