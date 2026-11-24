package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** 模型路由与级联（1.7 / 1.8）：成本-延迟-意图打分 + fallback 链 + 版本锁定。 */
@Service
public class LlmRouter {
    private final Map<String, Map<String, String>> specs;
    public LlmRouter(@org.springframework.beans.factory.annotation.Qualifier("providerSpecs")
                     Map<String, Map<String, String>> specs) { this.specs = specs; }

    public Map<String, Object> route(String intent, Double maxCost, Integer latencySla,
                                     boolean sensitive, String modelPin, String actual) {
        boolean pinOk = modelPin == null || modelPin.isBlank() || modelPin.equals(actual);
        List<Map<String, Object>> cands = new ArrayList<>();
        for (var e : specs.entrySet()) {
            Map<String, String> p = e.getValue();
            double cost = (1200 * Double.parseDouble(p.get("costIn"))
                    + 300 * Double.parseDouble(p.get("costOut"))) / 1_000_000;
            int lat = p.get("url").contains("localhost") ? 2200 : 1000;
            if (maxCost != null && cost > maxCost) continue;
            if (latencySla != null && lat > latencySla) continue;
            double score = cost * 100 + lat / 1000.0
                    - (sensitive && "ollama".equals(e.getKey()) ? 2.0 : 0);
            cands.add(Map.of("provider", e.getKey(), "score", score, "cost", cost,
                    "latency_ms", lat, "parallel_tools", p.get("parallelTools"),
                    "structured", p.get("structured")));
        }
        cands.sort((a, b) -> Double.compare((Double) a.get("score"), (Double) b.get("score")));
        String primary = cands.isEmpty() ? "ollama" : (String) cands.get(0).get("provider");
        if (sensitive) primary = "ollama";
        return Map.of("primary", primary, "fallback_chain",
                cands.stream().skip(1).limit(2).map(c -> c.get("provider")).toList(),
                "cascade", cands.size() > 1, "model_pin_ok", pinOk,
                "default_bias", "workflow > single-agent > multi-agent");
    }

    public Map<String, Object> providers() { return Map.copyOf(specs); }

    public List<Map<String, String>> optimizationOrder() {
        return List.of(Map.of("priority", "1", "action", "缓存"),
                Map.of("priority", "2", "action", "模型路由与级联"),
                Map.of("priority", "3", "action", "精简上下文"),
                Map.of("priority", "4", "action", "换更便宜模型"));
    }
}
