package com.xingtu.agent.infra;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.ArrayDeque;
import java.util.Deque;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Redis 访问封装：所有操作在 Redis 不可用时降级到本地缓存（有界 + TTL），保证业务不中断。
 */
@Component
public class RedisService {

    private static final Logger log = LoggerFactory.getLogger(RedisService.class);
    private static final int LOCAL_CACHE_LIMIT = 2000;

    private final StringRedisTemplate redis;
    private final Map<String, LocalEntry> localCache = new ConcurrentHashMap<>();
    private final Map<String, Deque<Long>> localWindows = new ConcurrentHashMap<>();
    private final AtomicLong localCounter = new AtomicLong(0L);

    private record LocalEntry(String value, long expireAtMillis) {
    }

    public RedisService(StringRedisTemplate redis) {
        this.redis = redis;
    }

    public void set(String key, String value, Duration ttl) {
        try {
            redis.opsForValue().set(key, value, ttl);
        } catch (RuntimeException e) {
            degrade("set", key, e);
            putLocal(key, value, ttl.toMillis());
        }
    }

    public String get(String key) {
        try {
            String value = redis.opsForValue().get(key);
            if (value != null) {
                return value;
            }
        } catch (RuntimeException e) {
            degrade("get", key, e);
        }
        LocalEntry entry = localCache.get(key);
        if (entry == null) {
            return null;
        }
        if (entry.expireAtMillis() > 0 && entry.expireAtMillis() < System.currentTimeMillis()) {
            localCache.remove(key);
            return null;
        }
        return entry.value();
    }

    public boolean setIfAbsent(String key, String value, Duration ttl) {
        try {
            Boolean result = redis.opsForValue().setIfAbsent(key, value, ttl);
            if (result != null) {
                return result;
            }
        } catch (RuntimeException e) {
            degrade("setIfAbsent", key, e);
        }
        String existing = get(key);
        if (existing != null) {
            return false;
        }
        putLocal(key, value, ttl.toMillis());
        return true;
    }

    public long increment(String key, Duration ttl) {
        try {
            Long value = redis.opsForValue().increment(key);
            if (value != null) {
                if (value == 1L) {
                    redis.expire(key, ttl);
                }
                return value;
            }
        } catch (RuntimeException e) {
            degrade("increment", key, e);
        }
        return localCounter.incrementAndGet();
    }

    /**
     * 滑动窗口计数：ZSET 存时间戳，先清理窗口外的，再统计窗口内的数量。
     */
    public long slidingWindowCount(String key, int windowSeconds) {
        long now = System.currentTimeMillis();
        long windowStart = now - windowSeconds * 1000L;
        try {
            redis.opsForZSet().add(key, now + "-" + UUID.randomUUID(), now);
            redis.opsForZSet().removeRangeByScore(key, 0d, windowStart);
            Long count = redis.opsForZSet().zCard(key);
            redis.expire(key, Duration.ofSeconds(windowSeconds + 5L));
            if (count != null) {
                return count;
            }
        } catch (RuntimeException e) {
            degrade("slidingWindowCount", key, e);
        }
        Deque<Long> window = localWindows.computeIfAbsent(key, k -> new ArrayDeque<>());
        synchronized (window) {
            while (!window.isEmpty() && window.peekFirst() < windowStart) {
                window.pollFirst();
            }
            window.addLast(now);
            return window.size();
        }
    }

    public void delete(String key) {
        try {
            redis.delete(key);
        } catch (RuntimeException e) {
            degrade("delete", key, e);
        }
        localCache.remove(key);
        localWindows.remove(key);
    }

    public boolean healthy() {
        try {
            redis.hasKey("ecom:health:probe");
            return true;
        } catch (RuntimeException e) {
            return false;
        }
    }

    private void putLocal(String key, String value, long ttlMillis) {
        if (localCache.size() > LOCAL_CACHE_LIMIT) {
            localCache.clear();
        }
        localCache.put(key, new LocalEntry(value, System.currentTimeMillis() + ttlMillis));
    }

    private void degrade(String op, String key, RuntimeException e) {
        log.debug("Redis {} 失败，降级到本地缓存 key={} : {}", op, key, e.getMessage());
    }
}
