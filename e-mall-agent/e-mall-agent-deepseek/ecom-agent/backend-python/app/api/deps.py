"""API 依赖聚合：把认证、数据库、角色校验集中在一处，路由文件只 import 这里。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议
# 职责：API 依赖聚合：把认证、数据库、角色校验集中在一处，路由文件只 import 这里
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

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
