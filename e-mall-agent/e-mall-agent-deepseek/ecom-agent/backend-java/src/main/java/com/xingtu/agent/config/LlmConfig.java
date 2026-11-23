package com.xingtu.agent.config;

import com.xingtu.agent.llm.MockChatModel;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.net.http.HttpClient;
import java.time.Duration;

/**
 * LLM 基础设施：共享 HTTP 客户端 + Mock 模型。
 * 真实供应商统一走 OpenAI 兼容协议（见 OpenAiCompatibleProvider），不依赖 SDK Builder。
 */
@Configuration
public class LlmConfig {

    @Bean
    public HttpClient llmHttpClient(AppProperties props) {
        return HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(Math.max(1, props.getLlm().getTimeoutSeconds())))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    @Bean
    public MockChatModel mockChatModel() {
        return new MockChatModel();
    }
}
