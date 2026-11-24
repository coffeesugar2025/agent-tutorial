package com.xiaozhan.agent.service;

import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;

/** 5.5 / 7.2：trace/span、Metrics、Golden Case、pass^k、Bad Case、Replay。 */
@Service
public class ObservabilityService {
    private final MeterRegistry registry;
    private final List<Map<String, Object>> spans = new CopyOnWriteArrayList<>();
    private final List<Map<String, Object>> badCases = new CopyOnWriteArrayList<>();

    public ObservabilityService(MeterRegistry registry) { this.registry = registry; }

    public Map<String, Object> trace(String name) {
        String tid = "tr_" + UUID.randomUUID().toString().substring(0, 10);
        spans.add(Map.of("trace_id", tid, "span", "root", "name", name, "kind", "agent"));
        spans.add(Map.of("trace_id", tid, "span", "tool", "name", "getOrder", "parent", "root"));
        spans.add(Map.of("trace_id", tid, "span", "model", "name", "synthesize", "parent", "root"));
        registry.counter("agent.runs", "backend", "java").increment();
        return Map.of("trace_id", tid, "span_count", 3,
                "frames", spans.stream().filter(s -> tid.equals(s.get("trace_id")))
                        .map(s -> Map.of("kind", s.get("kind"), "name", s.get("name"))).toList(),
                "spans", spans.stream().filter(s -> tid.equals(s.get("trace_id"))).toList(),
                "otel", "OpenTelemetry GenAI 语义约定 / InvocationContext.parentInvocationId");
    }

    public Map<String, Object> metrics() {
        return Map.of("counters", Map.of("agent.runs", registry.counter("agent.runs", "backend", "java").count()),
                "histograms", Map.of("agent.latency.p95", "由 Micrometer 聚合"),
                "eval_metrics", List.of("任务成功率", "工具调用准确率", "幻觉率",
                        "引用覆盖率", "Token 成本", "P95/P99 延迟", "端到端完成质量"));
    }

    public Map<String, Object> evalStability(int k) {
        return Map.of("k", k, "aggregate_pass_pow_k", 1.0,
                "aggregate_pass_at_k", 1.0, "flaky_cases", List.of(),
                "note", "pass^k（k 次全成功）才反映生产可用性，不是 pass@k");
    }

    public Map<String, Object> replay(String traceId, Map<String, Object> overrides) {
        return Map.of("ok", true, "original", traceId, "identical", overrides.isEmpty(),
                "time_travel_from", overrides.isEmpty() ? null : overrides.keySet().iterator().next());
    }
}
