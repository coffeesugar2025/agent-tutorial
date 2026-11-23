package com.xingtu.agent.llm;

import com.xingtu.agent.common.TokenEstimator;

/**
 * Mock 供应商：走 LangChain4j ChatLanguageModel 接口，token 用量由本地估算。
 */
public class MockLlmProvider implements LlmProvider {

    private final MockChatModel model;

    public MockLlmProvider(MockChatModel model) {
        this.model = model;
    }

    @Override
    public String name() {
        return "mock";
    }

    @Override
    public String model() {
        return "mock-chat";
    }

    @Override
    public boolean configured() {
        return true;
    }

    @Override
    public Result chat(Request request) {
        long start = System.currentTimeMillis();
        String text = model.chatViaLangChain4j(request);
        long latency = System.currentTimeMillis() - start;
        int promptTokens = 0;
        for (Message message : request.messages()) {
            promptTokens += TokenEstimator.estimate(message.content());
        }
        int completionTokens = TokenEstimator.estimate(text);
        return new Result(text, promptTokens, completionTokens, name(), model(), latency);
    }
}
