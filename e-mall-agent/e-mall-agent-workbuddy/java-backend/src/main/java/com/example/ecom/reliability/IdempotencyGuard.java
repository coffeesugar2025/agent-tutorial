package com.example.ecom.reliability;

import com.example.ecom.security.ApiException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;

import java.time.Instant;
import java.util.concurrent.ConcurrentHashMap;

/** 幂等键：同一 Idempotency-Key 在 TTL 内重复提交直接拒绝。 */
@Component
public class IdempotencyGuard {

    private record Entry(long expiresAt, String fingerprint) {}

    private final ConcurrentHashMap<String, Entry> seen = new ConcurrentHashMap<>();
    private final long ttlSeconds;

    public IdempotencyGuard(@org.springframework.beans.factory.annotation.Value("${app.idempotency.ttl-seconds:300}") long ttlSeconds) {
        this.ttlSeconds = ttlSeconds;
    }

    /** 首次调用写入并返回 true；重复调用返回 false。 */
    public boolean acquire(String key, String fingerprint) {
        if (key == null || key.isBlank()) return true;
        long now = Instant.now().getEpochSecond();
        Entry fresh = new Entry(now + ttlSeconds, fingerprint == null ? "" : fingerprint);
        Entry previous = seen.putIfAbsent(key, fresh);
        if (previous == null) return true;
        if (previous.expiresAt() <= now) {
            seen.put(key, fresh);
            return true;
        }
        return false;
    }

    public void requireNew(String key, String fingerprint) {
        if (!acquire(key, fingerprint)) {
            throw new ApiException(HttpStatus.CONFLICT, "重复请求（幂等键已存在）");
        }
    }

    public void forget(String key) {
        if (key != null) seen.remove(key);
    }
}
