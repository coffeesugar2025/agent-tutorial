package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/** 第 5 章：错误分类 / 幂等 / 熔断 / 降级 / 终止条件。 */
@Service
public class ReliabilityService {
    private static final Set<String> RETRYABLE = Set.of("rate_limit", "timeout", "server", "network");
    private final Map<String, Object> idem = new ConcurrentHashMap<>();
    private final AtomicInteger failures = new AtomicInteger();

    public Map<String, Object> classify(String message) {
        String m = message.toLowerCase();
        String kind = "unknown";
        if (m.contains("429") || m.contains("rate limit")) kind = "rate_limit";
        else if (m.contains("timeout") || m.contains("超时")) kind = "timeout";
        else if (m.contains("502") || m.contains("503") || m.contains("upstream")) kind = "server";
        else if (m.contains("invalid") || m.contains("422") || m.contains("参数")) kind = "validation";
        else if (m.contains("403") || m.contains("unauthorized") || m.contains("越权")) kind = "auth";
        else if (m.contains("quota") || m.contains("预算")) kind = "quota_hard";
        boolean retry = RETRYABLE.contains(kind);
        return Map.of("kind", kind, "retryable", retry,
                "suggested_action", retry ? "指数退避+抖动后重试" : "修正参数/转人工，不重试");
    }

    public Map<String, Object> idempotent(String op, Map<String, Object> payload,
                                          java.util.function.Supplier<Object> work) {
        String key = op + ":" + Integer.toHexString(payload.toString().hashCode());
        Object cached = idem.get(key);
        if (cached != null) return Map.of("replayed", true, "result", cached, "key", key);
        Object r = work.get();
        idem.put(key, r);
        return Map.of("replayed", false, "result", r, "key", key);
    }

    public Map<String, Object> circuit(int threshold) {
        int n = failures.incrementAndGet();
        String state = n >= threshold ? "open" : "closed";
        return Map.of("state", state, "failures", n, "allow", !state.equals("open"));
    }

    public Map<String, Object> terminate(int steps, int maxSteps, boolean repeated) {
        String r = steps > maxSteps ? "max_steps" : (repeated ? "repeated_action" : "continue");
        return Map.of("reason", r, "steps", steps);
    }
}
