"""认证接口：登录、当前用户。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, get_current_user, get_db
from app.common.envelope import ok
from app.infra import models_obs
from app.infra.db import session_scope
from app.security.auth import authenticate_user, create_access_token
from app.security.ratelimit import limit_login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


class LoginReq(BaseModel):
    """登录请求。"""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@router.post("/login", summary="用户名密码登录")
def login(req: LoginReq, request: Request, db: Session = Depends(get_db)):
    """校验账号密码并签发 JWT。"""
    client_ip = request.client.host if request.client else None
    limit_login(req.username, client_ip)

    user = authenticate_user(db, req.username, req.password)
    token, expires_in = create_access_token(
        user_id=int(user.id),
        username=user.username,
        roles=[r.strip() for r in (user.roles or "USER").split(",") if r.strip()],
    )
    _audit_login(int(user.id), user.username, client_ip)
    return ok(
        {
            "token": token,
            "expiresIn": expires_in,
            "user": {
                "id": user.id,
                "username": user.username,
                "displayName": user.display_name,
                "roles": [r.strip() for r in (user.roles or "USER").split(",") if r.strip()],
            },
        }
    )


@router.get("/me", summary="当前登录用户")
def me(user: CurrentUser = Depends(get_current_user)):
    return ok(user.to_vo())


def _audit_login(user_id: int, username: str, ip: str | None) -> None:
    try:
        with session_scope() as db:
            db.add(
                models_obs.AuditLog(
                    user_id=user_id,
                    action="auth.login",
                    target=username[:128],
                    detail={"ip": ip},
                    ip=ip,
                )
            )
    except Exception as exc:  # noqa: BLE001 - 审计失败不阻断登录
        logger.warning("登录审计写入失败: %s", exc)


__all__ = ["router"]
