package com.example.ecom.agent;

import com.example.ecom.domain.ChatResponse.ToolCall;
import com.example.ecom.observability.Metrics;
import com.example.ecom.reliability.RetryHelper;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.agent.tool.ToolSpecification;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.ToolExecutionResultMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 手写 ReAct / Agent Loop：工具调用 → 结果回填 → 再推理，最大轮次保护。
 * 等价于 AiServices 声明式 agent，但可显式暴露 toolCalls 与每轮节点用于前端可视化。
 * 替换点：若需要声明式写法，可用 AiServices.builder(Assistant.class).chatModel(...).tools(tools).build()。
 */
@Component
public class ReActRunner {

    public record Result(String answer, List<ToolCall> toolCalls, List<String> nodes, boolean degraded) {}

    private final ChatModel chatModel;
    private final List<ToolSpecification> toolSpecs;
    private final Tools tools;
    private final RetryHelper retry;
    private final Metrics metrics;
    private final int maxRounds;

    public ReActRunner(ChatModel chatModel, List<ToolSpecification> toolSpecs, Tools tools,
                       RetryHelper retry, Metrics metrics,
                       @Value("${app.agent.max-rounds:4}") int maxRounds) {
        this.chatModel = chatModel;
        this.toolSpecs = toolSpecs;
        this.tools = tools;
        this.retry = retry;
        this.metrics = metrics;
        this.maxRounds = Math.max(1, maxRounds);
    }

    /** ReAct 循环。messages 已含 SystemMessage（Context Engineering 的产物）。 */
    public Result run(List<ChatMessage> messages, boolean allowTools) {
        List<ChatMessage> working = new ArrayList<>(messages);
        List<ToolCall> calls = new ArrayList<>();
        List<String> nodes = new ArrayList<>();
        List<ToolSpecification> specs = allowTools && !toolSpecs.isEmpty() ? toolSpecs : List.of();

        for (int round = 1; round <= maxRounds; round++) {
            nodes.add("llm");
            ChatRequest request = ChatRequest.builder()
                    .messages(working)
                    .toolSpecifications(specs)
                    .build();
            ChatResponse response = retry.retry(() -> chatModel.chat(request), 2, 150L);
            AiMessage ai = response.aiMessage();

            if (ai.hasToolExecutionRequests()) {
                nodes.add("tool");
                working.add(ai);
                for (ToolExecutionRequest tr : ai.toolExecutionRequests()) {
                    Tools.ToolResult result = tools.invoke(tr);
                    calls.add(new ToolCall(tr.name(), result.content()));
                    working.add(ToolExecutionResultMessage.from(tr, result.content()));
                    metrics.increment("tool.executed");
                }
                continue;
            }

            String text = ai.text();
            return new Result(text == null ? "" : text, calls, nodes, false);
        }

        metrics.increment("agent.max_rounds");
        return new Result("（已达最大推理轮次 " + maxRounds + "，已停止工具调用以避免死循环）",
                calls, nodes, true);
    }

    /** 可靠性：LLM 异常时降级为规则答案，不向前端抛错。 */
    public Result runWithFallback(List<ChatMessage> messages, boolean allowTools, String fallbackAnswer) {
        try {
            return run(messages, allowTools);
        } catch (RuntimeException e) {
            metrics.increment("agent.degraded");
            return new Result(fallbackAnswer, List.of(), List.of("fallback"), true);
        }
    }
}
