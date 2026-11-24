package com.xingtu.agent.llm;

// ═══════ 文件级能力标注 ═══════
// [CAP-02] 模型接入与输出控制  |  [CAP-18] 成本与模型工程
// 职责：Mock 供应商：走 LangChain4j ChatLanguageModel 接口，token 用量由本地估算
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

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
