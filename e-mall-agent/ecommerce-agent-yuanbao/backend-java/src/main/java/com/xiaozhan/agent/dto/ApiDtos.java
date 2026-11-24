package com.xiaozhan.agent.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import java.util.List;
import java.util.Map;

public final class ApiDtos {
    private ApiDtos() {}
    public record ChatRequest(String message, String threadId, String userId, String tenantId) {}
    public record ChatResponse(String answer, String traceId, List<String> toolsUsed,
                               String backend, Map<String, Object> cards) {}
    public record CapabilityResponse(String backend, String framework, int chapters,
                                    Map<String, Object> modules) {}
    /** 同时接受 snake_case（Python 契约 / 前端 CitationView）与 camelCase。 */
    public record RagRequest(String question, String mode,
                             @JsonAlias("top_k") int topK,
                             @JsonAlias("user_id") String userId,
                             @JsonAlias("tenant_id") String tenantId,
                             List<String> roles) {}
    public record ApprovalRequest(String tool, Map<String, Object> args, String reason) {}
    public record EvalResponse(int total, double passRate, Map<String, Object> aggregate) {}
}
