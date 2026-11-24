"""RBAC：角色解析与依赖注入式校验。

角色常量与 ``parse_roles`` 放在叶子模块 :mod:`app.security.roles`，
避免与 :mod:`app.security.auth` 形成循环导入。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-15] 安全与合规
# 职责：RBAC：角色解析与依赖注入式校验
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends

from app.common.errors import forbidden
from app.security.auth import CurrentUser, get_current_user
from app.security.roles import ALL_ROLES, ROLE_ADMIN, ROLE_OPS, ROLE_USER, parse_roles


def has_role(user: CurrentUser | None, *roles: str) -> bool:
    """是否具备其中任一角色；ADMIN 隐含全部权限。"""
    if user is None:
        return False
    owned = {r.upper() for r in user.roles}
    if ROLE_ADMIN in owned:
        return True
    return any(role.upper() in owned for role in roles)


def ensure_role(user: CurrentUser, *roles: str, message: str = "无权限访问该资源") -> None:
    """不具备角色时直接抛 40300。"""
    if not has_role(user, *roles):
        raise forbidden(message)


def require_roles(*roles: str) -> Callable[..., CurrentUser]:
    """生成 FastAPI 依赖：要求任一角色。

    用法：``user: CurrentUser = Depends(require_roles("ADMIN"))``
    """

    def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        ensure_role(user, *roles)
        return user

    return _dependency


require_admin = require_roles(ROLE_ADMIN)
require_ops = require_roles(ROLE_OPS, ROLE_ADMIN)


__all__ = [
    "ALL_ROLES",
    "ROLE_ADMIN",
    "ROLE_OPS",
    "ROLE_USER",
    "ensure_role",
    "has_role",
    "parse_roles",
    "require_admin",
    "require_ops",
    "require_roles",
]
