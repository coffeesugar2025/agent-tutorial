package com.example.ecom.observability;

import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/** 轻量计数指标：trace / 工具调用 / 重试 / 降级 / 拒绝 等。 */
@Component
public class Metrics {

    private final ConcurrentHashMap<String, AtomicLong> counters = new ConcurrentHashMap<>();

    public void increment(String name) {
        counters.computeIfAbsent(name, k -> new AtomicLong()).incrementAndGet();
    }

    public void increment(String name, long delta) {
        counters.computeIfAbsent(name, k -> new AtomicLong()).addAndGet(delta);
    }

    public long get(String name) {
        AtomicLong v = counters.get(name);
        return v == null ? 0 : v.get();
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> result = new ConcurrentHashMap<>();
        counters.forEach((k, v) -> result.put(k, v.get()));
        return result;
    }
}
