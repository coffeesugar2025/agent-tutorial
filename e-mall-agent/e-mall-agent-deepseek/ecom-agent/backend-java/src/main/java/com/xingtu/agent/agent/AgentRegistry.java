package com.xingtu.agent.agent;

import org.springframework.stereotype.Component;

import java.util.EnumMap;
import java.util.Map;

/**
 * Agent 注册表：按类型取 Agent 实例，SUPERVISOR 额外提供路由能力。
 */
@Component
public class AgentRegistry {

    private final Map<AgentType, Agent> agents = new EnumMap<>(AgentType.class);
    private final SupervisorAgent supervisor;

    public AgentRegistry(SupervisorAgent supervisor, ShoppingAgent shopping, ServiceAgent service,
                         OpsAgent ops) {
        this.supervisor = supervisor;
        agents.put(AgentType.SUPERVISOR, supervisor);
        agents.put(AgentType.SHOPPING, shopping);
        agents.put(AgentType.SERVICE, service);
        agents.put(AgentType.OPS, ops);
    }

    public Agent get(AgentType type) {
        Agent agent = agents.get(type);
        return agent == null ? supervisor : agent;
    }

    public SupervisorAgent supervisor() {
        return supervisor;
    }

    public Map<AgentType, Agent> all() {
        return Map.copyOf(agents);
    }
}
