package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.*;

/** 2.5 / 2.6：Token 预算、上下文压缩、三层记忆、冲突消解。 */
@Service
public class MemoryContextService {
    public Map<String, Object> budget() {
        return Map.of("total", 4096, "system", 600, "tools", 500,
                "output", 512, "retrieved", 900, "history", 1584,
                "layout", List.of("system_rules(稳定)", "tool_definitions(稳定)",
                        "few_shot(稳定)", "long_term_memory(半稳)", "session_summary(变)",
                        "retrieved_evidence(变)", "user_question(最变)"));
    }

    public Map<String, Object> compress(List<Map<String, Object>> messages, int recentTurns) {
        List<Map<String, Object>> systems = messages.stream()
                .filter(m -> "system".equals(m.get("role"))).toList();
        int old = Math.max(0, messages.size() - systems.size() - recentTurns * 2);
        List<Map<String, Object>> out = new ArrayList<>(systems);
        if (old > 0) out.add(Map.of("role", "system", "content", "历史会话摘要：保留金额/SKU/状态等关键事实"));
        out.addAll(messages.subList(Math.max(systems.size(), messages.size() - recentTurns * 2), messages.size()));
        return Map.of("messages", out, "original_tokens", messages.size() * 60,
                "compressed_tokens", out.size() * 60, "summarized_turns", old,
                "strategy", "system+recent+extractive-summary");
    }

    public Map<String, Object> layers(String userId, String threadId) {
        return Map.of("conversation", Map.of("mechanism", "ChatMemory/@MemoryId",
                        "scope", "thread:" + threadId, "survives_new_thread", false),
                "long_term", Map.of("mechanism", "Redis + MySQL users/profile",
                        "scope", "users/" + userId, "survives_new_thread", true),
                "user", Map.of("mechanism", "白名单事实抽取 + 版本合并", "survives_new_thread", true));
    }

    public Map<String, Object> merge(String oldBudget, String newBudget) {
        boolean conflict = oldBudget != null && !oldBudget.equals(newBudget);
        return Map.of("written", List.of("budget_max"), "conflict", conflict,
                "resolution", "显式用户表述覆盖，旧值留审计轨迹；30 天半衰期");
    }
}
