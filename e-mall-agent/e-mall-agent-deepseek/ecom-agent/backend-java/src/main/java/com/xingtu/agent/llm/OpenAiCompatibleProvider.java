package com.xingtu.agent.llm;

import com.xingtu.agent.common.TokenEstimator;
import com.xingtu.agent.config.AppProperties;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import dev.langchain4j.model.openai.OpenAiChatModel;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * OpenAI 兼容协议的供应商实现（DeepSeek / 通义千问 compatible-mode / OpenAI / Ollama）。
 *
 * <p>真正的模型调用交给 <b>LangChain4j</b> 的 {@link OpenAiChatModel}：
 * 由它负责 HTTP 传输、鉴权、响应解析与错误映射，本类只做三件事——
 * 把内部 {@link LlmProvider.Message} 转成 LangChain4j 消息、调用、把结果归一。</p>
 *
 * <p>为什么仍保留自己的 {@code LlmProvider} 抽象：Agent 运行时需要统一的
 * 「候选链 + 熔断 + 计费」视图，而不同框架版本对模型对象的封装方式差异较大，
 * 用一层薄适配隔离后，升级框架不会波及业务代码。</p>
 */
public class OpenAiCompatibleProvider implements LlmProvider {

    private final String name;
    private final String baseUrl;
    private final String apiKey;
    private final String model;
    private final int timeoutSeconds;

    /** 懒加载：首次调用时才构建，避免启动期因 Key 缺失而失败。 */
    private volatile ChatLanguageModel delegate;

    public OpenAiCompatibleProvider(String name, AppProperties.Provider provider, int timeoutSeconds,
                                    HttpClient httpClient) {
        this.name = name;
        this.baseUrl = trimSlash(provider.getBaseUrl());
        this.apiKey = provider.getApiKey() == null ? "" : provider.getApiKey();
        this.model = provider.getModel();
        this.timeoutSeconds = timeoutSeconds;
        // httpClient 仅为向后兼容保留：传输层已交给 LangChain4j 管理
    }

    @Override
    public String name() {
        return name;
    }

    @Override
    public String model() {
        return model;
    }

    @Override
    public boolean configured() {
        if (baseUrl == null || baseUrl.isBlank() || model == null || model.isBlank()) {
            return false;
        }
        // Ollama 本地部署通常不需要 Key
        return "ollama".equals(name) || !apiKey.isBlank();
    }

    @Override
    public Result chat(Request request) {
        long start = System.currentTimeMillis();
        if (!configured()) {
            throw new LlmException(name + " 未配置 baseUrl / apiKey / model");
        }

        List<ChatMessage> messages = toLangChain4jMessages(request.messages());
        ChatRequest chatRequest = ChatRequest.builder()
                .messages(messages)
                .build();

        ChatResponse response;
        try {
            response = model().chat(chatRequest);
        } catch (LlmException e) {
            throw e;
        } catch (RuntimeException e) {
            throw new LlmException(name + " 调用失败: " + e.getMessage(), e);
        }

        String text = extractText(response);
        if (text == null || text.isBlank()) {
            throw new LlmException(name + " 返回空内容");
        }

        int promptTokens = 0;
        int completionTokens = 0;
        try {
            // LangChain4j 不同小版本的 TokenUsage 取值可能为 Integer 或 int，
            // 统一按 int 接收，null 时由下面的估算兜底。
            var usage = response.tokenUsage();
            if (usage != null) {
                promptTokens = usage.inputTokenCount();
                completionTokens = usage.outputTokenCount();
            }
        } catch (RuntimeException ignored) {
            // 供应商未返回 usage，走本地估算
        }
        if (promptTokens <= 0) {
            promptTokens = estimatePromptTokens(request);
        }
        if (completionTokens <= 0) {
            completionTokens = TokenEstimator.estimate(text);
        }

        return new Result(text, promptTokens, completionTokens, name, model,
                System.currentTimeMillis() - start);
    }

    /** 构建（并缓存）LangChain4j 模型。 */
    private ChatLanguageModel model() {
        ChatLanguageModel local = delegate;
        if (local == null) {
            synchronized (this) {
                local = delegate;
                if (local == null) {
                    local = OpenAiChatModel.builder()
                            .baseUrl(baseUrl)
                            .apiKey(apiKey)
                            .modelName(model)
                            .timeout(Duration.ofSeconds(timeoutSeconds))
                            .maxRetries(0)
                            .build();
                    delegate = local;
                }
            }
        }
        return local;
    }

    /** 把内部消息转成 LangChain4j 消息；未知角色按用户消息处理。 */
    private List<ChatMessage> toLangChain4jMessages(List<Message> source) {
        List<ChatMessage> messages = new ArrayList<>();
        for (Message message : source) {
            String role = message.role() == null ? "user" : message.role();
            String content = message.content() == null ? "" : message.content();
            switch (role) {
                case "system" -> messages.add(SystemMessage.from(content));
                case "assistant" -> messages.add(AiMessage.from(content));
                default -> messages.add(UserMessage.from(content));
            }
        }
        return messages;
    }

    /** 从 ChatResponse 里取文本，兼容 aiMessage 为空的情况。 */
    private String extractText(ChatResponse response) {
        if (response == null) {
            return "";
        }
        AiMessage aiMessage = response.aiMessage();
        if (aiMessage == null) {
            return "";
        }
        String text = aiMessage.text();
        return text == null ? "" : text;
    }

    private int estimatePromptTokens(Request request) {
        int total = 0;
        for (Message message : request.messages()) {
            total += TokenEstimator.estimate(message.content());
        }
        return total;
    }

    private String trimSlash(String url) {
        if (url == null) {
            return "";
        }
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }
}
