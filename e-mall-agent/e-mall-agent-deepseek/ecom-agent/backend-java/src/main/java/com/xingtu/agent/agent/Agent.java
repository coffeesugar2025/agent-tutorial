package com.xingtu.agent.agent;

import java.util.List;

/**
 * Agent 定义：类型 + 系统提示 + 工具白名单。运行时由同一个 ReAct 循环驱动。
 */
public interface Agent {

    AgentType type();

    String systemPrompt();

    List<String> toolNames();
}
