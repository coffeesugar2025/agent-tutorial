"""Agent 子系统：运行时、路由、提示词、终止策略。"""

# ═══════ 文件级能力标注 ═══════
# [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
# 职责：Agent 子系统：运行时、路由、提示词、终止策略
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from app.agents.runtime import AgentRuntime
from app.agents.state import AGENT_TYPES, AgentEvent, AgentState

__all__ = ["AGENT_TYPES", "AgentEvent", "AgentRuntime", "AgentState"]
