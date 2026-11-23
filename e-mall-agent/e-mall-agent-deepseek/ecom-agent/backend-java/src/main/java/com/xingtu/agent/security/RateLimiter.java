package com.xingtu.agent.security;

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.RedisService;
import org.springframework.stereotype.Component;

/**
 * 限流：Redis 滑动窗口（ZSET），Redis 不可用时 RedisService 自动降级为本地窗口。
 * 维度：用户 + 场景；阈值 RATE_LIMIT_PER_MINUTE。
 */
@Component
public class RateLimiter {

    private final RedisService redisService;
    private final AppProperties props;

    public RateLimiter(RedisService redisService, AppProperties props) {
        this.redisService = redisService;
        this.props = props;
    }

    public void check(long userId, String scope) {
        int limit = props.getAgent().getRateLimitPerMinute();
        if (limit <= 0) {
            return;
        }
        String key = "ecom:rl:" + scope + ":" + userId;
        long count = redisService.slidingWindowCount(key, 60);
        if (count > limit) {
            throw BizException.rateLimited("请求过于频繁，请稍后再试（限制 " + limit + " 次/分钟）");
        }
    }

    public long current(long userId, String scope) {
        return redisService.slidingWindowCount("ecom:rl:" + scope + ":" + userId, 60);
    }
}
