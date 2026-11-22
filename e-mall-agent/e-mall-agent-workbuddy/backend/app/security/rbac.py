"""Role-based access control + lightweight HMAC token (production: replace with OAuth2/JWT)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from contextvars import ContextVar
from typing import Any, Iterable

from ..domain.models import User

ALL_PERMISSIONS = {
    "product:read", "chat:use", "order:read", "order:create", "order:refund",
    "order:manage", "audit:read", "trace:read", "user:manage",
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "guest": {"product:read", "chat:use"},
    "customer": {"product:read", "chat:use", "order:read", "order:create", "order:refund"},
    "service": {"product:read", "chat:use", "order:read", "order:refund",
                "order:manage", "audit:read", "trace:read"},
    "admin": set(ALL_PERMISSIONS),
}

TOOL_PERMISSIONS: dict[str, str] = {
    "search_products": "product:read",
    "get_product": "product:read",
    "check_inventory": "product:read",
    "rag_search": "chat:use",
    "create_order": "order:create",
    "list_orders": "order:read",
    "get_order": "order:read",
    "initiate_refund": "order:refund",
}


def anonymous_user() -> User:
    return User(id="anonymous", name="访客", role="guest")


_current_user: ContextVar[User | None] = ContextVar("ecom_current_user", default=None)


def set_current_user(user: User) -> Any:
    """Bind the acting user to the current request/task (contextvar-safe)."""
    return _current_user.set(user)


def reset_current_user(token: Any) -> None:
    _current_user.reset(token)


def get_current_user() -> User:
    return _current_user.get() or anonymous_user()


def permissions_for(role: str) -> list[str]:
    return sorted(ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["guest"]))


def has_permission(user: User, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(user.role, set())


def require_permission(user: User, permission: str) -> None:
    if not has_permission(user, permission):
        raise PermissionError(f"角色 {user.role} 缺少权限: {permission}")


def can_access_customer(user: User, customer_id: str) -> bool:
    if user.role in ("admin", "service"):
        return True
    return user.role == "customer" and user.id == customer_id


def require_customer_scope(user: User, customer_id: str) -> None:
    if not can_access_customer(user, customer_id):
        raise PermissionError(f"用户 {user.id} 无权访问 {customer_id} 的订单数据")


def permission_for_tool(tool_name: str) -> str:
    return TOOL_PERMISSIONS.get(tool_name, "chat:use")


def filter_tools(tools: Iterable[Any], user: User) -> list[Any]:
    """Only expose tools the current role is allowed to invoke."""
    return [t for t in tools if has_permission(user, permission_for_tool(getattr(t, "name", "")))]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def issue_token(user: User, secret: str, ttl: int = 3600) -> str:
    payload = {"sub": user.id, "name": user.name, "role": user.role,
               "exp": int(time.time()) + ttl}
    body = _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def decode_token(token: str, secret: str) -> dict[str, Any] | None:
    try:
        body, signature = token.split(".", 1)
    except (ValueError, AttributeError):
        return None
    expected = _b64(hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    if payload.get("role") not in ROLE_PERMISSIONS:
        return None
    return payload


def user_from_payload(payload: dict[str, Any]) -> User:
    return User(id=str(payload["sub"]), name=str(payload.get("name", "")),
                role=str(payload.get("role", "guest")))
