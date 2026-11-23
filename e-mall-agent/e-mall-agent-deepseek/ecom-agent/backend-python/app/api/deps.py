"""API 依赖聚合：把认证、数据库、角色校验集中在一处，路由文件只 import 这里。"""

from __future__ import annotations

from app.infra.db import get_db
from app.security.auth import CurrentUser, get_current_user
from app.security.rbac import require_admin, require_ops, require_roles

__all__ = [
    "CurrentUser",
    "get_current_user",
    "get_db",
    "require_admin",
    "require_ops",
    "require_roles",
]
