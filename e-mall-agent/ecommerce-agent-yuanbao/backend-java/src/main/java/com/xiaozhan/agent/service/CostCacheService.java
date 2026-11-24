package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** 4.16 / 5.8：四级缓存 + 失效 + 每成功任务成本 + 预算终止。 */
@Service
public class CostCacheService {
    private final Map<String, Object> exact = new ConcurrentHashMap<>();
    private final Map<String, Object> retrieval = new ConcurrentHashMap<>();
    private final Map<String, Object> embedding = new ConcurrentHashMap<>();
    private final Map<String, Object> semantic = new ConcurrentHashMap<>();
    private double spent = 0, budget = 1.0;
    private int success = 0, failure = 0;

    public Map<String, Object> report() {
        double n = Math.max(1, success + failure);
        double rate = success / n;
        double perTask = spent / n;
        return Map.of("spent_usd", spent, "budget_usd", budget,
                "per_success_task", spent / Math.max(1, success),
                "effective_cost_usd", perTask / Math.max(1e-9, rate),
                "layers", Map.of("exact", exact.size(), "semantic", semantic.size(),
                        "retrieval", retrieval.size(), "embedding", embedding.size()),
                "optimization_order", List.of("缓存", "路由", "精简上下文", "换模型"));
    }

    public Map<String, Object> charge(String provider, int tin, int tout, double pin, double pout) {
        double c = (tin * pin + tout * pout) / 1_000_000;
        spent += c;
        return Map.of("cost_usd", c, "spent_usd", spent,
                "over_budget", spent > budget, "action", spent > budget ? "terminate" : "continue");
    }

    public Map<String, Object> invalidate(String docId) {
        int before = exact.size() + retrieval.size() + semantic.size() + embedding.size();
        exact.clear(); retrieval.clear(); semantic.clear(); embedding.clear();
        return Map.of("strategy", "purge", "doc_id", docId, "removed_before", before);
    }
}
