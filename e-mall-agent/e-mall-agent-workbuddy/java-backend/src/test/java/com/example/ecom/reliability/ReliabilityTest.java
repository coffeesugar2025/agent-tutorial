package com.example.ecom.reliability;

import com.example.ecom.observability.Metrics;
import org.junit.jupiter.api.Test;

import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

class ReliabilityTest {

    private final RetryHelper retry = new RetryHelper(new Metrics());

    @Test
    void retriesUntilSuccess() {
        AtomicInteger attempts = new AtomicInteger();
        String result = retry.retry(() -> {
            if (attempts.incrementAndGet() < 3) throw new IllegalStateException("flaky");
            return "ok";
        }, 4, 1L);
        assertEquals("ok", result);
        assertEquals(3, attempts.get());
    }

    @Test
    void fallbackUsedWhenAttemptsExhausted() {
        String result = retry.retryOrFallback(() -> {
            throw new IllegalStateException("down");
        }, () -> "rule-based", 2, 1L);
        assertEquals("rule-based", result);
    }

    @Test
    void idempotencyKeyRejectsDuplicate() {
        IdempotencyGuard guard = new IdempotencyGuard(300);
        assertTrue(guard.acquire("key-1", "fingerprint"));
        assertFalse(guard.acquire("key-1", "fingerprint"));
        assertThrows(com.example.ecom.security.ApiException.class,
                () -> guard.requireNew("key-1", "fingerprint"));
        guard.forget("key-1");
        assertTrue(guard.acquire("key-1", "fingerprint"));
    }
}
