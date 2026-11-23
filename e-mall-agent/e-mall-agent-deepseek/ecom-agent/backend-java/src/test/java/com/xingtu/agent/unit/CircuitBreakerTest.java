package com.xingtu.agent.unit;

import com.xingtu.agent.llm.CircuitBreaker;
import org.junit.jupiter.api.Test;

import java.time.Clock;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class CircuitBreakerTest {

    @Test
    void opensAfterThresholdThenRecoversThroughHalfOpen() throws InterruptedException {
        CircuitBreaker breaker = new CircuitBreaker(2, 150L, Clock.systemUTC());
        assertTrue(breaker.allowRequest("deepseek"));
        assertEquals(CircuitBreaker.CLOSED, breaker.state("deepseek"));

        breaker.recordFailure("deepseek");
        breaker.recordFailure("deepseek");
        assertEquals(CircuitBreaker.OPEN, breaker.state("deepseek"));
        assertFalse(breaker.allowRequest("deepseek"));

        Thread.sleep(220L);
        assertEquals(CircuitBreaker.HALF_OPEN, breaker.state("deepseek"));
        assertTrue(breaker.allowRequest("deepseek"));

        breaker.recordSuccess("deepseek", 120L);
        assertEquals(CircuitBreaker.CLOSED, breaker.state("deepseek"));
        assertEquals(3L, breaker.calls("deepseek"));
        assertEquals(40L, breaker.avgLatencyMs("deepseek"));
    }

    @Test
    void halfOpenFailureReopensImmediately() throws InterruptedException {
        CircuitBreaker breaker = new CircuitBreaker(1, 100L, Clock.systemUTC());
        breaker.recordFailure("qwen");
        assertEquals(CircuitBreaker.OPEN, breaker.state("qwen"));
        assertFalse(breaker.allowRequest("qwen"));

        Thread.sleep(160L);
        assertTrue(breaker.allowRequest("qwen"));
        breaker.recordFailure("qwen");
        assertEquals(CircuitBreaker.OPEN, breaker.state("qwen"));
        assertFalse(breaker.allowRequest("qwen"));
    }

    @Test
    void unknownProviderDefaultsToClosed() {
        CircuitBreaker breaker = new CircuitBreaker(3, 1_000L, Clock.systemUTC());
        assertEquals(CircuitBreaker.CLOSED, breaker.state("unknown"));
        assertEquals(0L, breaker.calls("unknown"));
        assertEquals(0L, breaker.avgLatencyMs("unknown"));
        assertTrue(breaker.allowRequest("unknown"));
    }

    @Test
    void resetClearsState() {
        CircuitBreaker breaker = new CircuitBreaker(1, 1_000L, Clock.systemUTC());
        breaker.recordFailure("openai");
        assertEquals(CircuitBreaker.OPEN, breaker.state("openai"));
        breaker.reset("openai");
        assertEquals(CircuitBreaker.CLOSED, breaker.state("openai"));
    }
}
