package com.example.ecom.reliability;

import com.example.ecom.observability.Metrics;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.function.Supplier;

/** 重试 + 指数退避：LLM / 外部基础设施调用失败时有限重试。 */
@Component
public class RetryHelper {

    private final Metrics metrics;

    public RetryHelper(Metrics metrics) {
        this.metrics = metrics;
    }

    public <T> T retry(Supplier<T> action, int maxAttempts, long initialBackoffMs) {
        if (maxAttempts < 1) maxAttempts = 1;
        RuntimeException last = null;
        for (int attempt = 1; attempt <= maxAttempts; attempt++) {
            try {
                return action.get();
            } catch (RuntimeException e) {
                last = e;
                metrics.increment("retry.attempt");
                if (attempt == maxAttempts) break;
                try {
                    Thread.sleep(Duration.ofMillis(initialBackoffMs * (1L << Math.min(attempt - 1, 5))).toMillis());
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }
        throw last == null ? new IllegalStateException("重试失败") : last;
    }

    /** 静默降级：重试耗尽后返回 fallback，并计数。 */
    public <T> T retryOrFallback(Supplier<T> action, Supplier<T> fallback,
                                 int maxAttempts, long initialBackoffMs) {
        try {
            return retry(action, maxAttempts, initialBackoffMs);
        } catch (RuntimeException e) {
            metrics.increment("fallback.used");
            return fallback.get();
        }
    }
}
