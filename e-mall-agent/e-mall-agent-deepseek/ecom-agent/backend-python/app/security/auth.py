"""认证：密码哈希、JWT 签发/校验、当前用户依赖。

* 密码：优先 passlib[bcrypt]，不可用时退回 ``bcrypt`` 模块（两者哈希格式一致，
  ``$2b$`` 前缀互通，便于容器间迁移）；
* JWT：HS256，payload 含 ``sub/username/roles/exp``（docs/03 §0.4）；
* SSE 等无法自定义请求头的场景允许 ``?token=`` 传递（仅用于 GET 流式接口）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.common.errors import unauthorized
from app.common.timeutil import utcnow
from app.config import settings
from app.infra.db import get_db
from app.infra.models import SysUser
from app.security.roles import parse_roles

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)

try:  # pragma: no cover - 取决于运行环境
    from passlib.context import CryptContext

    _pwd_context: CryptContext | None = CryptContext(schemes=["bcrypt"], deprecated="auto")
except Exception:  # noqa: BLE001
    _pwd_context = None

try:  # pragma: no cover
    import bcrypt as _bcrypt
except Exception:  # noqa: BLE001
    _bcrypt = None


@dataclass
class CurrentUser:
    """当前登录用户（轻量，避免把 ORM 对象传出请求作用域）。"""

    id: int
    username: str
    display_name: str
    roles: list[str] = field(default_factory=lambda: ["USER"])
    email: str | None = None

    def to_vo(self) -> dict[str, object]:
        return {
            "id": self.id,
            "username": self.username,
            "displayName": self.display_name,
            "roles": self.roles,
        }


# ---------------------------------------------------------------------------
# 密码
# ---------------------------------------------------------------------------
def hash_password(plain: str) -> str:
    """生成 BCrypt 哈希（长度截断到 72 字节，规避 bcrypt 限制）。"""
    raw = plain.encode("utf-8")[:72]
    if _pwd_context is not None:
        try:
            return _pwd_context.hash(raw.decode("utf-8", errors="ignore"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("passlib 哈希失败，回退 bcrypt: %s", exc)
    if _bcrypt is None:
        raise unauthorized("密码组件不可用，请联系管理员")
    return _bcrypt.hashpw(raw, _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码；任何后端异常都视为校验失败（不泄露内部细节）。"""
    if not plain or not hashed:
        return False
    raw = plain.encode("utf-8")[:72]
    if _pwd_context is not None:
        try:
            return bool(_pwd_context.verify(raw.decode("utf-8", errors="ignore"), hashed))
        except Exception:  # noqa: BLE001
            pass
    if _bcrypt is None:
        return False
    try:
        return bool(_bcrypt.checkpw(raw, hashed.encode("utf-8")))
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(
    user_id: int,
    username: str,
    roles: list[str] | None = None,
    expires_in: int | None = None,
) -> tuple[str, int]:
    """签发 access token，返回 ``(token, expires_in_seconds)``。"""
    ttl = expires_in or settings.jwt_expire_seconds
    expire_at = utcnow() + timedelta(seconds=ttl)
    payload = {
        "sub": str(user_id),
        "username": username,
        "roles": roles or ["USER"],
        "exp": expire_at,
        "iat": utcnow(),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, ttl


def decode_token(token: str) -> dict[str, object]:
    """解析并校验 token；失败抛 40100。"""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise unauthorized("无效的访问令牌") from exc
    return payload


def user_from_payload(payload: dict[str, object]) -> CurrentUser:
    """从 token payload 还原轻量用户。"""
    try:
        user_id = int(str(payload.get("sub")))
    except (TypeError, ValueError) as exc:
        raise unauthorized("令牌缺少有效用户标识") from exc
    roles = payload.get("roles") or ["USER"]
    if isinstance(roles, str):
        role_list = parse_roles(roles)
    else:
        role_list = [str(r) for r in roles]  # type: ignore[union-attr]
    return CurrentUser(
        id=user_id,
        username=str(payload.get("username") or ""),
        display_name=str(payload.get("username") or ""),
        roles=role_list,
    )


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """FastAPI 依赖：解析 Bearer token（SSE 场景兼容 ?token=）。"""
    token = credentials.credentials if credentials else request.query_params.get("token", "")
    if not token:
        raise unauthorized()
    payload = decode_token(token)
    user = user_from_payload(payload)
    row = db.get(SysUser, user.id)
    if row is None or row.status != 1:
        raise unauthorized("用户不存在或已被禁用")
    user.username = row.username
    user.display_name = row.display_name
    user.roles = parse_roles(row.roles)
    user.email = row.email
    return user


def authenticate_user(db: Session, username: str, password: str) -> SysUser:
    """用户名密码登录：失败统一提示，避免枚举用户名。"""
    row = db.query(SysUser).filter(SysUser.username == username).one_or_none()
    if row is None or row.status != 1 or not verify_password(password, row.password_hash):
        raise unauthorized("用户名或密码错误")
    return row


def ensure_demo_password() -> str:
    """开发脚手架用：返回演示账号的统一明文口令。"""
    return "Passw0rd!"


__all__ = [
    "CurrentUser",
    "authenticate_user",
    "bearer_scheme",
    "create_access_token",
    "decode_token",
    "ensure_demo_password",
    "get_current_user",
    "hash_password",
    "user_from_payload",
    "verify_password",
]
