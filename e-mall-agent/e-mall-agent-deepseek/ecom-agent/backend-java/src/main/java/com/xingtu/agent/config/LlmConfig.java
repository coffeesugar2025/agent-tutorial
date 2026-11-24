package com.xingtu.agent.config;

// ═══════ 文件级能力标注 ═══════
// [CAP-02] 模型接入与输出控制  |  [CAP-14] 可靠性/降级  （支撑）
// 职责：LLM 基础设施：共享 HTTP 客户端 + Mock 模型
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

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
