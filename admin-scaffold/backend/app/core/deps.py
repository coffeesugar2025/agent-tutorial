from dataclasses import dataclass, field

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt import ExpiredSignatureError, InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import decode_token
from app.db.mysql import get_db
from app.db.redis import redis_client
from app.models import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


@dataclass
class CurrentUser:
    id: int
    username: str
    nickname: str
    is_superuser: bool
    roles: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)

    def has(self, code: str) -> bool:
        return self.is_superuser or "*" in self.permissions or code in self.permissions


async def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未登录或凭证已失效",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_error
    try:
        payload = decode_token(token)
    except (ExpiredSignatureError, InvalidTokenError):
        raise credentials_error
    if payload.get("type") != "access":
        raise credentials_error
    if await redis_client.is_blacklisted(payload.get("jti", "")):
        raise credentials_error

    result = await db.execute(
        select(User)
        .options(selectinload(User.roles).selectinload(Role.permissions))
        .where(User.id == int(payload["sub"]))
    )
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_error

    perms: set[str] = set()
    for role in user.roles:
        if not role.is_active:
            continue
        for p in role.permissions:
            perms.add(p.code)
    return CurrentUser(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        is_superuser=user.is_superuser,
        roles=[r.code for r in user.roles],
        permissions=perms,
    )


def require_perm(code: str):
    """接口级权限依赖：require_perm('user:create')"""

    async def _checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has(code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"缺少权限：{code}",
            )
        return user

    return _checker
