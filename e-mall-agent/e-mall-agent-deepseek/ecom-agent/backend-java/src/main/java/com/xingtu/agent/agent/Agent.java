package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：Agent 定义：类型 + 系统提示 + 工具白名单
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import java.util.List;

/**
 * Agent 定义：类型 + 系统提示 + 工具白名单。运行时由同一个 ReAct 循环驱动。
 */
public interface Agent {

    AgentType type();

    String systemPrompt();

    List<String> toolNames();
}
