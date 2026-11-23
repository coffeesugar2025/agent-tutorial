package com.example.ecom.domain;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** POST /api/chat 请求体：同时接受 threadId 与前端使用的 thread_id。 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ChatRequest(
        String message,
        @JsonAlias("thread_id") String threadId
) {
    public ChatRequest {
        if (threadId == null || threadId.isBlank()) threadId = "default";
    }

    public String threadId() {
        return threadId == null || threadId.isBlank() ? "default" : threadId;
    }
}
