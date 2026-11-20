from datetime import datetime, timezone
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- 统一响应 ----------
class R(BaseModel, Generic[T]):
    code: int = 0
    message: str = "ok"
    data: T | None = None


def ok(data: Any = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}


def page_payload(items: list, total: int, page: int, size: int) -> dict:
    return {"items": items, "total": total, "page": page, "size": size}


# ---------- 认证 ----------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class RefreshIn(BaseModel):
    refresh_token: str


class ProfileOut(BaseModel):
    id: int
    username: str
    nickname: str
    is_superuser: bool
    roles: list[str]
    permissions: list[str]


class MenuOut(BaseModel):
    path: str
    title: str
    icon: str
    perm: str


# ---------- 用户 ----------
class UserOut(ORMModel):
    id: int
    username: str
    nickname: str
    email: str
    phone: str
    is_active: bool
    is_superuser: bool
    created_at: datetime
    roles: list[str] = []


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    nickname: str = ""
    email: str = ""
    phone: str = ""
    is_active: bool = True
    role_ids: list[int] = []


class UserUpdate(BaseModel):
    nickname: str | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    role_ids: list[int] | None = None


class ResetPasswordIn(BaseModel):
    password: str = Field(min_length=6, max_length=128)


# ---------- 角色 ----------
class RoleOut(ORMModel):
    id: int
    code: str
    name: str
    description: str
    is_active: bool
    created_at: datetime
    permission_ids: list[int] = []


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    is_active: bool = True
    permission_ids: list[int] = []


class RoleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    permission_ids: list[int] | None = None


class PermAssignIn(BaseModel):
    permission_ids: list[int]


# ---------- 权限 ----------
class PermissionOut(ORMModel):
    id: int
    code: str
    name: str
    module: str
    kind: str
    sort: int
    created_at: datetime


class PermissionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=96)
    name: str = Field(min_length=1, max_length=64)
    module: str = "system"
    kind: str = "api"
    sort: int = 0


class PermissionUpdate(BaseModel):
    name: str | None = None
    module: str | None = None
    kind: str | None = None
    sort: int | None = None


# ---------- 审计 ----------
class AuditEvent(BaseModel):
    ts: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    username: str
    action: str
    resource: str
    detail: str = ""
    ip: str = ""


# ---------- 通用查询 ----------
class PageQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=200)
    keyword: str = ""
