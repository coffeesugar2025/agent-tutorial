package com.xingtu.agent.llm;

import com.xingtu.agent.config.AppProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 熔断器：连续失败达到阈值后进入 OPEN，冷却期后半开试探。
 * CLOSED -> (失败阈值) -> OPEN -> (冷却结束) -> HALF_OPEN -> 成功 CLOSED / 失败 OPEN。
 */
@Component
public class CircuitBreaker {

    public static final String CLOSED = "CLOSED";
    public static final String OPEN = "OPEN";
    public static final String HALF_OPEN = "HALF_OPEN";

    private static final int DEFAULT_FAILURE_THRESHOLD = 3;
    private static final long DEFAULT_OPEN_MILLIS = 30_000L;

    private final int failureThreshold;
    private final long openMillis;
    private final Clock clock;
    private final Map<String, State> states = new ConcurrentHashMap<>();

    @Autowired
    public CircuitBreaker(AppProperties props) {
        this(DEFAULT_FAILURE_THRESHOLD, DEFAULT_OPEN_MILLIS, Clock.systemUTC());
    }

    /** 测试友好构造器：可注入固定时钟与阈值。 */
    public CircuitBreaker(int failureThreshold, long openMillis, Clock clock) {
        this.failureThreshold = Math.max(1, failureThreshold);
        this.openMillis = Math.max(1L, openMillis);
        this.clock = clock;
    }

    public boolean allowRequest(String name) {
        State state = states.computeIfAbsent(name, key -> new State());
        synchronized (state) {
            if (OPEN.equals(state.status)) {
                if (clock.millis() - state.openedAt >= openMillis) {
                    state.status = HALF_OPEN;
                    return true;
                }
                return false;
            }
            return true;
        }
    }

    public void recordSuccess(String name, long latencyMs) {
        State state = states.computeIfAbsent(name, key -> new State());
        synchronized (state) {
            state.calls++;
            state.totalLatency += Math.max(0L, latencyMs);
            state.failures = 0;
            state.status = CLOSED;
        }
    }

    public void recordFailure(String name) {
        State state = states.computeIfAbsent(name, key -> new State());
        synchronized (state) {
            state.calls++;
            state.failures++;
            if (state.failures >= failureThreshold || HALF_OPEN.equals(state.status)) {
                state.status = OPEN;
                state.openedAt = clock.millis();
            }
        }
    }

    public String state(String name) {
        State state = states.get(name);
        if (state == null) {
            return CLOSED;
        }
        synchronized (state) {
            if (OPEN.equals(state.status) && clock.millis() - state.openedAt >= openMillis) {
                return HALF_OPEN;
            }
            return state.status;
        }
    }

    public long calls(String name) {
        State state = states.get(name);
        return state == null ? 0L : state.calls;
    }

    public long avgLatencyMs(String name) {
        State state = states.get(name);
        if (state == null || state.calls == 0L) {
            return 0L;
        }
        return state.totalLatency / state.calls;
    }

    public void reset(String name) {
        states.remove(name);
    }

    private static final class State {
        private String status = CLOSED;
        private int failures = 0;
        private long openedAt = 0L;
        private long calls = 0L;
        private long totalLatency = 0L;
    }
}
