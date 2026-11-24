package com.xiaozhan.agent.config;

import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.openai.OpenAiChatModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 多模型网关（总纲 1.1 / 1.7）。
 *
 * 坑位（已核实）：LangChain4j 1.x 把 ChatLanguageModel 改名成 ChatModel；
 * 且同类型多个 ChatModel bean 直接注入会导致启动失败。因此这里：
 *   - 只暴露一个 @Primary ChatModel 给 @AiService(wiringMode=EXPLICIT) 使用
 *   - 其余供应商放进 Map，由 LlmRouter 按其选择后显式构造，不做类型注入
 */
@Configuration
public class LlmConfig {

    @Bean("primaryChatModel")
    @Primary
    public ChatModel primaryChatModel(
            @Value("${langchain4j.open-ai.chat-model.base-url}") String baseUrl,
            @Value("${langchain4j.open-ai.chat-model.api-key}") String apiKey,
            @Value("${langchain4j.open-ai.chat-model.model-name}") String modelName) {
        return OpenAiChatModel.builder()
                .baseUrl(baseUrl).apiKey(apiKey).modelName(modelName)
                .temperature(0.0).timeout(Duration.ofSeconds(30))
                .logRequests(false).logResponses(false)
                .build();
    }

    @Bean("providerSpecs")
    public Map<String, Map<String, String>> providerSpecs() {
        Map<String, Map<String, String>> m = new LinkedHashMap<>();
        m.put("deepseek", Map.of("url", "https://api.deepseek.com/v1", "model", "deepseek-chat",
                "costIn", "0.27", "costOut", "1.10", "parallelTools", "true", "structured", "json_mode"));
        m.put("qwen", Map.of("url", "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model", "qwen-plus", "costIn", "0.40", "costOut", "1.20",
                "parallelTools", "true", "structured", "json_schema"));
        m.put("glm", Map.of("url", "https://open.bigmodel.cn/api/paas/v4", "model", "glm-4-flash",
                "costIn", "0.10", "costOut", "0.10", "parallelTools", "false", "structured", "json_mode"));
        m.put("ollama", Map.of("url", "http://localhost:11434/v1", "model", "qwen2.5:7b",
                "costIn", "0", "costOut", "0", "parallelTools", "false", "structured", "grammar"));
        return m;
    }
}
