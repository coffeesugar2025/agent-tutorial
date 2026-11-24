package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：商品导购 Agent：负责选品、比价、对比推荐
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 商品导购 Agent：负责选品、比价、对比推荐。
 */
@Component
public class ShoppingAgent implements Agent {

    @Override
    public AgentType type() {
        return AgentType.SHOPPING;
    }

    @Override
    public String systemPrompt() {
        return "你是星图商城的资深导购。目标：在用户预算内给出 2~3 款可解释的推荐，"
                + "说明取舍（拍照/性能/续航/价格），不夸大参数，不承诺库存以外的信息。"
                + "需要商品数据时必须调用工具，不要凭空编造 sku、价格或库存。";
    }

    @Override
    public List<String> toolNames() {
        return AgentType.SHOPPING.toolNames();
    }
}
