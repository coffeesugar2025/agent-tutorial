package com.example.ecom.domain;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;
import java.util.Map;

/**
 * POST /api/chat 响应。
 * 同时输出驼峰（契约要求 traceId/toolCalls）与下划线（现有前端 ChatResult 期望 trace_id）字段，
 * 保证 Python/Java 双后端的前端零改动复用。
 */
@JsonInclude(JsonInclude.Include.ALWAYS)
public class ChatResponse {

    public record ToolCall(String name, String content) {}

    private String answer;
    private String route;
    private String traceId;
    private List<ToolCall> toolCalls;
    private Map<String, Object> context;

    public ChatResponse() {
    }

    public ChatResponse(String answer, String route, String traceId,
                        List<ToolCall> toolCalls, Map<String, Object> context) {
        this.answer = answer;
        this.route = route;
        this.traceId = traceId;
        this.toolCalls = toolCalls == null ? List.of() : toolCalls;
        this.context = context == null ? Map.of() : context;
    }

    public String getAnswer() { return answer; }
    public void setAnswer(String answer) { this.answer = answer; }
    public String getRoute() { return route; }
    public void setRoute(String route) { this.route = route; }
    public String getTraceId() { return traceId; }
    public void setTraceId(String traceId) { this.traceId = traceId; }
    @JsonProperty("trace_id")
    public String getTraceIdSnake() { return traceId; }
    public List<ToolCall> getToolCalls() { return toolCalls; }
    public void setToolCalls(List<ToolCall> toolCalls) { this.toolCalls = toolCalls; }
    public Map<String, Object> getContext() { return context; }
    public void setContext(Map<String, Object> context) { this.context = context; }
}
