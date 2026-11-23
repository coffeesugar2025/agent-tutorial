package com.example.ecom.agent;

import com.example.ecom.observability.Metrics;
import com.example.ecom.reliability.RetryHelper;
import dev.langchain4j.agent.tool.ToolExecutionRequest;
import dev.langchain4j.data.message.AiMessage;
import dev.langchain4j.data.message.UserMessage;
import dev.langchain4j.model.chat.ChatModel;
import dev.langchain4j.model.chat.request.ChatRequest;
import dev.langchain4j.model.chat.response.ChatResponse;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class ReActRunnerTest {

    /** 用真实子类替身替代 Mockito 类 mock（Java 25 + 旧 ByteBuddy 无法 mock 具体类）。 */
    private Tools stubTools(AtomicInteger calls) {
        return new Tools(null, null, null, null, null, null) {
            @Override
            public ToolResult invoke(ToolExecutionRequest request) {
                calls.incrementAndGet();
                return new ToolResult(true, "[{\"name\":\"耳机\"}]");
            }
        };
    }

    @Test
    void toolCallIsExecutedThenFedBackForFinalAnswer() {
        ChatModel model = mock(ChatModel.class);
        ToolExecutionRequest call = ToolExecutionRequest.builder()
                .id("call-1").name("searchProducts").arguments("{\"query\":\"耳机\"}").build();
        ChatResponse first = ChatResponse.builder().aiMessage(AiMessage.from(List.of(call))).build();
        ChatResponse second = ChatResponse.builder().aiMessage(AiMessage.from("找到耳机")).build();
        when(model.chat(any(ChatRequest.class))).thenReturn(first, second);

        AtomicInteger calls = new AtomicInteger();
        ReActRunner runner = new ReActRunner(model, List.of(), stubTools(calls),
                new RetryHelper(new Metrics()), new Metrics(), 3);
        ReActRunner.Result result = runner.run(List.of(UserMessage.from("搜索耳机")), true);

        assertEquals("找到耳机", result.answer());
        assertEquals(1, result.toolCalls().size());
        assertEquals("searchProducts", result.toolCalls().get(0).name());
        assertTrue(result.nodes().contains("tool"));
        assertEquals(1, calls.get());
    }

    @Test
    void stopsAtMaxRounds() {
        ChatModel model = mock(ChatModel.class);
        ToolExecutionRequest call = ToolExecutionRequest.builder()
                .id("c").name("searchProducts").arguments("{}").build();
        when(model.chat(any(ChatRequest.class))).thenAnswer(inv ->
                ChatResponse.builder().aiMessage(AiMessage.from(List.of(call))).build());

        AtomicInteger calls = new AtomicInteger();
        ReActRunner runner = new ReActRunner(model, List.of(), stubTools(calls),
                new RetryHelper(new Metrics()), new Metrics(), 2);
        ReActRunner.Result result = runner.run(List.of(UserMessage.from("循环")), true);

        assertTrue(result.degraded());
        assertTrue(result.answer().contains("最大推理轮次"));
        assertEquals(2, result.toolCalls().size());
        assertEquals(2, calls.get());
    }
}
