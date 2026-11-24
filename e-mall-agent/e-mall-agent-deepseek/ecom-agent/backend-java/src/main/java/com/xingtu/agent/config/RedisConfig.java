package com.xingtu.agent.config;

// ═══════ 文件级能力标注 ═══════
// [CAP-02] 模型接入与输出控制  |  [CAP-14] 可靠性/降级  （支撑）
// 职责：Redis 序列化统一为 String，避免默认 JDK 序列化导致 redis-cli 不可读
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.serializer.StringRedisSerializer;

/**
 * Redis 序列化统一为 String，避免默认 JDK 序列化导致 redis-cli 不可读。
 * 连接工厂沿用 Spring Boot 自动配置（Lettuce）。
 */
@Configuration
public class RedisConfig {

    @Bean
    public RedisTemplate<String, String> redisTemplate(StringRedisTemplate stringRedisTemplate) {
        RedisTemplate<String, String> template = new RedisTemplate<>();
        template.setConnectionFactory(stringRedisTemplate.getConnectionFactory());
        StringRedisSerializer serializer = new StringRedisSerializer();
        template.setKeySerializer(serializer);
        template.setValueSerializer(serializer);
        template.setHashKeySerializer(serializer);
        template.setHashValueSerializer(serializer);
        template.afterPropertiesSet();
        return template;
    }
}
