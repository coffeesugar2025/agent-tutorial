package com.example.ecom.config;

import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.ChatMessageDeserializer;
import dev.langchain4j.data.message.ChatMessageSerializer;
import dev.langchain4j.store.memory.chat.ChatMemoryStore;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Redis 会话记忆（MessageWindowChatMemory 的持久化后端）。
 * Redis 连接失败时自动降级到进程内 Map，保证对话链路不中断。
 */
public class RedisChatMemoryStore implements ChatMemoryStore {

    private static final String PREFIX = "ecom:chat:memory:";
    private static final Duration TTL = Duration.ofHours(24);

    private final StringRedisTemplate redis;
    private final ConcurrentHashMap<Object, String> fallback = new ConcurrentHashMap<>();

    public RedisChatMemoryStore(StringRedisTemplate redis) {
        this.redis = redis;
    }

    @Override
    public List<ChatMessage> getMessages(Object memoryId) {
        String json = null;
        try {
            json = redis.opsForValue().get(PREFIX + memoryId);
        } catch (Exception ignored) {
            json = fallback.get(memoryId);
        }
        if (json == null || json.isBlank()) return List.of();
        try {
            return ChatMessageDeserializer.messagesFromJson(json);
        } catch (Exception e) {
            return List.of();
        }
    }

    @Override
    public void updateMessages(Object memoryId, List<ChatMessage> messages) {
        String json = ChatMessageSerializer.messagesToJson(messages);
        fallback.put(memoryId, json);
        try {
            redis.opsForValue().set(PREFIX + memoryId, json, TTL);
        } catch (Exception ignored) {
            // Redis 不可用时已在 fallback 中保留会话
        }
    }

    @Override
    public void deleteMessages(Object memoryId) {
        fallback.remove(memoryId);
        try {
            redis.delete(PREFIX + memoryId);
        } catch (Exception ignored) {
            // ignore
        }
    }
}
