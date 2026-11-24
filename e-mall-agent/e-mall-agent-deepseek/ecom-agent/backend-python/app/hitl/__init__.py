"""HITL 审批子系统。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-10] 人机协作 HITL
# 职责：HITL 审批子系统
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from app.hitl import approval

__all__ = ["approval"]
