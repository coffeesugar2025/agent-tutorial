package com.example.ecom.config;

import dev.langchain4j.agent.tool.ToolSpecification;
import dev.langchain4j.agent.tool.ToolSpecifications;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.store.memory.chat.ChatMemoryStore;
import dev.langchain4j.store.memory.chat.InMemoryChatMemoryStore;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.openai.OpenAiChatModel;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.List;

/**
 * LangChain4j 1.24.0 最小稳定 API 配置。
 * - DeepSeek / 通义千问均走 OpenAI 兼容协议，用 OpenAiChatModel + 不同 base-url 接入；
 * - 无 API Key 时降级到 RuleBasedChatModel，全链路零网络可跑；
 * - 会话记忆默认进程内，app.memory.redis-enabled=true 时切到 Redis（失败自动回退内存）。
 */
@Configuration
public class LangChain4jConfig {

    @Value("${app.llm.deepseek.api-key:}") private String deepseekKey;
    @Value("${app.llm.deepseek.base-url:}") private String deepseekBaseUrl;
    @Value("${app.llm.deepseek.model:}") private String deepseekModel;
    @Value("${app.llm.qwen.api-key:}") private String qwenKey;
    @Value("${app.llm.qwen.base-url:}") private String qwenBaseUrl;
    @Value("${app.llm.qwen.model:}") private String qwenModel;
    @Value("${app.llm.temperature:0.2}") private double temperature;
    @Value("${app.llm.timeout-seconds:20}") private int timeoutSeconds;
    @Value("${app.llm.max-retries:2}") private int maxRetries;
    @Value("${app.llm.provider:auto}") private String provider;

    @Bean("deepseekChatModel")
    public ChatModel deepseekChatModel() {
        return buildOrFallback(deepseekKey, deepseekBaseUrl, deepseekModel);
    }

    @Bean("qwenChatModel")
    public ChatModel qwenChatModel() {
        return buildOrFallback(qwenKey, qwenBaseUrl, qwenModel);
    }

    /** 主 ChatModel：按 LLM_PROVIDER 路由，默认 auto（DeepSeek 优先）。 */
    @Bean
    @Primary
    public ChatModel chatModel(@Qualifier("deepseekChatModel") ChatModel deepseek,
                               @Qualifier("qwenChatModel") ChatModel qwen) {
        String p = provider == null ? "auto" : provider.toLowerCase();
        ChatModel delegate = switch (p) {
            case "deepseek" -> deepseek;
            case "qwen" -> qwen;
            case "offline" -> new RuleBasedChatModel();
            default -> {
                if (hasText(deepseekKey)) yield deepseek;
                if (hasText(qwenKey)) yield qwen;
                yield new RuleBasedChatModel();
            }
        };
        return new RoutingChatModel(delegate, p);
    }

    private ChatModel buildOrFallback(String key, String baseUrl, String model) {
        if (!hasText(key)) return new RuleBasedChatModel();
        return OpenAiChatModel.builder()
                .apiKey(key)
                .baseUrl(baseUrl)
                .modelName(model)
                .temperature(temperature)
                .timeout(Duration.ofSeconds(timeoutSeconds))
                .maxRetries(maxRetries)
                .build();
    }

    private static boolean hasText(String s) {
        return s != null && !s.isBlank();
    }

    /** 工具规格由 @Tool 注解自动生成（最小稳定 API：ToolSpecifications）。 */
    @Bean
    public List<ToolSpecification> toolSpecifications(
            com.example.ecom.agent.Tools tools) {
        return ToolSpecifications.toolSpecificationsFrom(tools);
    }

    /** Redis 会话记忆；未启用时纯内存。 */
    @Bean
    public ChatMemoryStore chatMemoryStore(
            @Value("${app.memory.redis-enabled:false}") boolean redisEnabled,
            org.springframework.beans.factory.ObjectProvider<StringRedisTemplate> redisTemplate) {
        if (redisEnabled) {
            StringRedisTemplate template = redisTemplate.getIfAvailable();
            if (template != null) return new RedisChatMemoryStore(template);
        }
        return new InMemoryChatMemoryStore();
    }

    /** 离线规则模型：LLM 不可用时保证 /api/chat 仍能返回有依据的答案。 */
    public static class RuleBasedChatModel implements ChatModel {
        @Override
        public ChatResponse chat(ChatRequest chatRequest) {
            String input = "";
            List<ChatMessage> messages = chatRequest.messages();
            for (int i = messages.size() - 1; i >= 0; i--) {
                if (messages.get(i) instanceof UserMessage um) {
                    input = um.singleText();
                    break;
                }
            }
            String answer = ruleAnswer(input);
            return ChatResponse.builder().aiMessage(AiMessage.from(answer)).build();
        }

        private String ruleAnswer(String input) {
            if (input == null || input.isBlank()) return "（离线规则模式）请输入您的问题。";
            String q = input.toLowerCase();
            if (q.contains("退款") || q.contains("退货")) {
                return "（离线规则模式）退款申请将在订单状态为已支付/已发货时受理；金额超过阈值的退款需要人工审批（confirm=true）。";
            }
            if (q.contains("订单")) {
                return "（离线规则模式）您可以查询自己的订单，客服与管理员可跨客户查询；订单履约状态为 created→paid→shipped→delivered。";
            }
            if (q.contains("商品") || q.contains("价格") || q.contains("库存") || q.contains("耳机")) {
                return "（离线规则模式）商品信息以 /api/products 为准，当前支持按分类与关键词检索，并可查询实时库存。";
            }
            return "（离线规则模式）我是电商智能助手，当前未配置大模型密钥，以上答案由规则引擎生成。配置 DEEPSEEK_API_KEY 或 QWEN_API_KEY 后可获得语义理解与工具调用能力。";
        }
    }

    /** 多模型路由：对外只有一个 ChatModel bean，避免 Spring 注入歧义。 */
    public static class RoutingChatModel implements ChatModel {
        private final ChatModel delegate;
        private final String provider;
        public RoutingChatModel(ChatModel delegate, String provider) {
            this.delegate = delegate;
            this.provider = provider;
        }
        @Override
        public ChatResponse chat(ChatRequest request) {
            return delegate.chat(request);
        }
        /** LangChain4j 1.24.0 的 ChatModel.provider() 返回 ModelProvider 枚举。 */
        @Override
        public dev.langchain4j.model.ModelProvider provider() {
            return "deepseek".equalsIgnoreCase(provider)
                    ? dev.langchain4j.model.ModelProvider.OPEN_AI
                    : "qwen".equalsIgnoreCase(provider)
                        ? dev.langchain4j.model.ModelProvider.OPEN_AI
                        : dev.langchain4j.model.ModelProvider.OTHER;
        }
    }
}
