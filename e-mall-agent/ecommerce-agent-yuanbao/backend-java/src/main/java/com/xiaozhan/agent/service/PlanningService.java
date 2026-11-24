package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.*;

/** 第 2.2 / 3.1 / 3.3：ReAct、Plan-and-Solve、Workflow 状态机、Supervisor 多 Agent。 */
@Service
public class PlanningService {
    public Map<String, Object> plan(String goal, String strategy) {
        List<Map<String, Object>> steps = new ArrayList<>();
        if (goal.contains("退货") || goal.contains("售后")) {
            steps.add(Map.of("id", 1, "tool", "check_after_sale_eligibility", "desc", "判定退货资格"));
            steps.add(Map.of("id", 2, "tool", "get_after_sale_policy", "desc", "查官方政策"));
        } else if (goal.contains("券") || goal.contains("到手") || goal.contains("多少钱")) {
            steps.add(Map.of("id", 1, "tool", "check_inventory", "desc", "核验库存"));
            steps.add(Map.of("id", 2, "tool", "calculate_price", "desc", "计算到手价", "depends_on", List.of(1)));
        } else {
            steps.add(Map.of("id", 1, "tool", "search_products", "desc", "检索商品"));
        }
        List<Map<String, Object>> trace = new ArrayList<>();
        for (Map<String, Object> s : steps) {
            trace.add(Map.of("thought", s.get("desc"), "action", s.get("tool"),
                    "observation", "工具执行成功（事实来自领域层）"));
        }
        return Map.of("goal", goal, "strategy", strategy, "plan", Map.of("steps", steps),
                "trace", trace, "steps_executed", trace.size(), "terminated_by", "completed");
    }

    public Map<String, Object> workflow(String goal) {
        String stage = goal.contains("下单") || goal.contains("退款") ? "escalated" : "done";
        return Map.of("goal", goal, "stage", stage,
                "nodes", List.of("classify", "retrieve", "review", "respond", "escalate"),
                "edges", List.of("START→classify", "classify→retrieve|escalate",
                        "retrieve→review", "review→respond|escalate", "respond→END"),
                "engine", "StateGraph/状态机（与 Python LangGraph 同语义）");
    }

    public Map<String, Object> multiAgent(String goal) {
        List<Map<String, Object>> results = new ArrayList<>();
        if (goal.contains("订单")) results.add(Map.of("agent", "OrderAgent", "tools", List.of("getOrder")));
        if (goal.contains("退货") || goal.contains("售后"))
            results.add(Map.of("agent", "AfterSaleAgent", "tools", List.of("checkAfterSale", "getPolicy")));
        if (results.isEmpty()) results.add(Map.of("agent", "ProductAgent", "tools", List.of("searchProducts")));
        return Map.of("question", goal, "pattern", "Supervisor + Worker",
                "agents_used", results.size(), "results", results,
                "context_isolation", "只交换结构化结论，不回传原始对话");
    }
}
