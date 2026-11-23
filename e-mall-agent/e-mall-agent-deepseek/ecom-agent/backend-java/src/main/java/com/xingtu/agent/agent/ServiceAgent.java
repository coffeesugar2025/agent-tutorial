package com.xingtu.agent.agent;

import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 订单售后 Agent：查订单、查物流、退款资格校验与退款申请（不可逆，需审批）。
 */
@Component
public class ServiceAgent implements Agent {

    @Override
    public AgentType type() {
        return AgentType.SERVICE;
    }

    @Override
    public String systemPrompt() {
        return "你是星图商城的售后专员。原则：先核实订单与政策，再给结论；"
                + "退款等不可逆操作必须先说明依据，并由系统走人工审批流程，不得声称已直接退款。"
                + "无法解决时调用 escalate_to_human 转人工。";
    }

    @Override
    public List<String> toolNames() {
        return AgentType.SERVICE.toolNames();
    }
}
