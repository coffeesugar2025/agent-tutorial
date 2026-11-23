"""角色常量与解析（无内部依赖的叶子模块）。

单独抽出来的原因：``auth`` 需要 ``parse_roles``，而 ``rbac`` 需要 ``auth`` 的
``CurrentUser`` 与 ``get_current_user``。若常量与解析函数留在 ``rbac`` 里，
两个模块会互相 import 形成环（Python 会报 "partially initialized module"）。
放在这个不依赖任何业务模块的叶子文件里，环就断了。
"""

from __future__ import annotations

ROLE_USER = "USER"
ROLE_OPS = "OPS"
ROLE_ADMIN = "ADMIN"
ALL_ROLES = (ROLE_USER, ROLE_OPS, ROLE_ADMIN)


def parse_roles(raw: str | None) -> list[str]:
    """``"USER,ADMIN"`` → ``["USER", "ADMIN"]``（大写、去空、去重、保序）。"""
    if not raw:
        return []
    seen: list[str] = []
    for item in str(raw).split(","):
        role = item.strip().upper()
        if role and role not in seen:
            seen.append(role)
    return seen


__all__ = ["ALL_ROLES", "ROLE_ADMIN", "ROLE_OPS", "ROLE_USER", "parse_roles"]
