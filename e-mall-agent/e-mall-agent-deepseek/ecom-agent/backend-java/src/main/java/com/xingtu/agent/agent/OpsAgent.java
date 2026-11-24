package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：经营分析 Agent：把自然语言问题转成只读 SQL，并用受限沙箱做聚合计算
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 经营分析 Agent：把自然语言问题转成只读 SQL，并用受限沙箱做聚合计算。
 */
@Component
public class OpsAgent implements Agent {

    @Override
    public AgentType type() {
        return AgentType.OPS;
    }

    @Override
    public String systemPrompt() {
        return "你是星图商城的经营分析师。原则：只做只读分析，SQL 必须是 SELECT 且带 LIMIT；"
                + "结论要给出数据口径（时间范围、过滤条件），数据为空时明确说明，不要编造数字。";
    }

    @Override
    public List<String> toolNames() {
        return AgentType.OPS.toolNames();
    }
}
