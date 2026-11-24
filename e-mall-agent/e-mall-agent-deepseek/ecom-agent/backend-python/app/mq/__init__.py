"""消息队列消费者与 handler 注册。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-14] 可靠性/降级
# 职责：消息队列消费者与 handler 注册
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from app.mq.consumers import register_all

__all__ = ["register_all"]
