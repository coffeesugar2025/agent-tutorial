"""路由集合。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-01] 交互协议
# 职责：路由集合
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from app.api.routes import admin, auth, chat, knowledge, orders, products, system

__all__ = ["admin", "auth", "chat", "knowledge", "orders", "products", "system"]
