package com.example.ecom.domain;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class ChatContractTest {

    private final ObjectMapper mapper = new ObjectMapper();

    @Test
    void acceptsThreadIdAlias() throws Exception {
        ChatRequest req = mapper.readValue("{\"message\":\"你好\",\"thread_id\":\"t-1\"}", ChatRequest.class);
        assertEquals("你好", req.message());
        assertEquals("t-1", req.threadId());
    }

    @Test
    void defaultsThreadId() throws Exception {
        ChatRequest req = mapper.readValue("{\"message\":\"你好\"}", ChatRequest.class);
        assertEquals("default", req.threadId());
    }

    @Test
    void productSerializesTagsAsArray() throws Exception {
        Product product = new Product("p-1", "耳机", "数码", 999.0, 3, List.of("降噪", "蓝牙"), "描述");
        String json = mapper.writeValueAsString(product);
        assertTrue(json.contains("\"tags\":[\"降噪\",\"蓝牙\"]"));
        assertFalse(json.contains("tagList"));
    }

    @Test
    void chatResponseExposesBothTraceIdNames() throws Exception {
        ChatResponse response = new ChatResponse("答案", "product", "trace-1", List.of(), java.util.Map.of());
        String json = mapper.writeValueAsString(response);
        assertTrue(json.contains("\"traceId\":\"trace-1\""));
        assertTrue(json.contains("\"trace_id\":\"trace-1\""));
    }
}
