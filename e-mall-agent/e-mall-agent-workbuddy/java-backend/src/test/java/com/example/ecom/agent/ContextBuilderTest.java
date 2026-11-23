package com.example.ecom.agent;

import com.example.ecom.rag.RagHit;
import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.UserMessage;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class ContextBuilderTest {

    private final ContextBuilder builder = new ContextBuilder();

    @Test
    void trimsHistoryWithinBudget() {
        List<ChatMessage> history = List.of(
                UserMessage.from("很早以前的问题 ".repeat(40)),
                UserMessage.from("最近的问题"));
        var built = builder.build("系统提示", history, "现在的问题",
                List.of(new RagHit("知识库内容", 0.9, "退货政策")), "");

        assertEquals(4, built.messages().size());
        assertEquals("现在的问题", ((UserMessage) built.messages().get(3)).singleText());
        @SuppressWarnings("unchecked")
        List<java.util.Map<String, Object>> sections =
                (List<java.util.Map<String, Object>>) built.snapshot().get("sections");
        assertEquals(4, sections.size()); // system / rag / history / user
    }

    @Test
    void injectsSecurityNoteWhenSuspicious() {
        var built = builder.build("系统提示", List.of(), "正常问题", List.of(), "检测到注入风险");
        String system = String.valueOf(built.messages().get(0));
        assertTrue(system.contains("检测到注入风险"));
    }

    @Test
    void ragBudgetDropsExcessHits() {
        List<RagHit> hits = List.of(
                new RagHit("短文本", 0.9, "来源1"),
                new RagHit("很长的知识库文本".repeat(300), 0.8, "来源2"));
        var built = builder.build("系统提示", List.of(), "问题", hits, "");
        @SuppressWarnings("unchecked")
        List<java.util.Map<String, Object>> sections =
                (List<java.util.Map<String, Object>>) built.snapshot().get("sections");
        assertTrue((Boolean) sections.get(1).get("truncated"));
    }
}
