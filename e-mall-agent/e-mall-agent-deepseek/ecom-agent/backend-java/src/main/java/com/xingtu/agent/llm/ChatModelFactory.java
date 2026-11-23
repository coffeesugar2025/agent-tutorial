package com.xingtu.agent.llm;

import com.xingtu.agent.config.AppProperties;
import org.springframework.stereotype.Component;

import java.net.http.HttpClient;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 模型供应商工厂：按名字创建供应商，并按优先级给出可用列表。
 *
 * <p>LLM_PRIMARY=mock 时只暴露 mock；否则按「主模型 + 兜底链」顺序返回，
 * 未配置 API Key 的供应商会被跳过（Ollama 本地部署例外）。</p>
 */
@Component
public class ChatModelFactory {

    private final AppProperties props;
    private final MockChatModel mockChatModel;
    private final HttpClient httpClient;
    private final FallbackChain fallbackChain;

    public ChatModelFactory(AppProperties props, MockChatModel mockChatModel, HttpClient llmHttpClient,
                            FallbackChain fallbackChain) {
        this.props = props;
        this.mockChatModel = mockChatModel;
        this.httpClient = llmHttpClient;
        this.fallbackChain = fallbackChain;
    }

    public LlmProvider create(String name) {
        if ("mock".equalsIgnoreCase(name)) {
            return new MockLlmProvider(mockChatModel);
        }
        AppProperties.Provider provider = props.getLlm().getProviders().get(name);
        if (provider == null) {
            throw new LlmException("未配置的模型供应商: " + name);
        }
        return new OpenAiCompatibleProvider(name, provider, props.getLlm().getTimeoutSeconds(), httpClient);
    }

    /** 已配置可用（含 mock 兜底）的供应商，按优先级排序。 */
    public List<LlmProvider> ordered() {
        List<LlmProvider> result = new ArrayList<>();
        for (String name : fallbackChain.names()) {
            LlmProvider provider = create(name);
            if (provider.configured()) {
                result.add(provider);
            }
        }
        if (result.isEmpty()) {
            result.add(new MockLlmProvider(mockChatModel));
        }
        return result;
    }

    /** 全部候选名（含未配置的，用于 /admin/models 展示）。 */
    public List<String> chainNames() {
        return fallbackChain.names();
    }

    /** 名字 -> 供应商（含未配置的），用于运营面板。 */
    public Map<String, LlmProvider> all() {
        Map<String, LlmProvider> map = new LinkedHashMap<>();
        for (String name : chainNames()) {
            map.put(name, create(name));
        }
        return map;
    }

    public MockChatModel mockChatModel() {
        return mockChatModel;
    }
}
