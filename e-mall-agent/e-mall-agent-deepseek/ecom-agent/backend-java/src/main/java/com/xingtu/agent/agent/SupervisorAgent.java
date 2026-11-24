package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：Supervisor：意图路由 + 结果聚合
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.Locale;

/**
 * Supervisor：意图路由 + 结果聚合。路由规则确定、可解释、可在 mock 模式下复现。
 */
@Component
public class SupervisorAgent implements Agent {

    public record Route(AgentType type, String reason) {
    }

    @Override
    public AgentType type() {
        return AgentType.SUPERVISOR;
    }

    @Override
    public String systemPrompt() {
        return "你是星图商城的调度中枢，负责判断用户意图并分派给合适的子 Agent。"
                + "你不直接调用工具，只输出路由结论。";
    }

    @Override
    public java.util.List<String> toolNames() {
        return java.util.List.of();
    }

    // ──────── [CAP-04] 规划与反思 ────────
    //   本处：意图路由（纯规则，可复现）
    //   域约束：路由只发生一次，不做多 Agent 互调，避免错误传播与成本放大
    public Route route(String question) {
        String q = question == null ? "" : question.toLowerCase(Locale.ROOT);
        if (containsAny(q, "报表", "销售额", "gmv", "营收", "营业额", "统计", "经营", "趋势", "转化率",
                "客单价", "成本", "模型调用", "热销", "销量排行")) {
            return new Route(AgentType.OPS, "经营分析意图");
        }
        if (containsAny(q, "订单", "物流", "快递", "到哪", "签收", "发货", "退款", "退货", "售后",
                "取消订单", "改地址", "保修", "维修", "投诉", "人工")) {
            return new Route(AgentType.SERVICE, "订单售后意图");
        }
        if (containsAny(q, "推荐", "手机", "买", "商品", "对比", "比价", "价格", "拍照", "耳机",
                "笔记本", "预算", "挑选", "哪款", "值得")) {
            return new Route(AgentType.SHOPPING, "商品导购意图");
        }
        if (containsAny(q, "政策", "规则", "怎么用", "说明", "手册", "faq")) {
            return new Route(AgentType.SERVICE, "知识问答意图");
        }
        return new Route(AgentType.SUPERVISOR, "通用咨询意图");
    }

    private boolean containsAny(String text, String... keywords) {
        for (String keyword : keywords) {
            if (text.contains(keyword)) {
                return true;
            }
        }
        return false;
    }
}
