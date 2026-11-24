package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：Agent 类型与工具集（docs/00 第 5 节）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import java.util.List;

/**
 * Agent 类型与工具集（docs/00 第 5 节）。
 */
public enum AgentType {

    SUPERVISOR("SUPERVISOR", "调度中枢", List.of()),
    SHOPPING("SHOPPING", "商品导购", List.of("search_products", "get_product_detail", "compare_products",
            "search_knowledge")),
    SERVICE("SERVICE", "订单与售后", List.of("get_order", "list_orders", "get_logistics",
            "check_refund_eligibility", "create_refund_request", "search_knowledge", "escalate_to_human")),
    OPS("OPS", "经营分析", List.of("text2sql", "run_python", "search_knowledge"));

    private final String code;
    private final String displayName;
    private final List<String> toolNames;

    AgentType(String code, String displayName, List<String> toolNames) {
        this.code = code;
        this.displayName = displayName;
        this.toolNames = toolNames;
    }

    public String code() {
        return code;
    }

    public String displayName() {
        return displayName;
    }

    public List<String> toolNames() {
        return toolNames;
    }

    public static AgentType from(String value) {
        if (value == null) {
            return SUPERVISOR;
        }
        for (AgentType type : values()) {
            if (type.code.equalsIgnoreCase(value.trim())) {
                return type;
            }
        }
        return SUPERVISOR;
    }
}
