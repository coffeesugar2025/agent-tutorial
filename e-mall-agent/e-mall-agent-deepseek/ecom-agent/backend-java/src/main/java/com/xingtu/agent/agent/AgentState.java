package com.xingtu.agent.agent;

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.rag.Citation;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Agent 运行时状态：步数、token 预算、成本、工具调用轨迹、无进展与循环检测计数。
 * 终止条件（docs/00 第 5 节）全部从这里读取，便于单测。
 */
public class AgentState {

    public record ToolInvocation(String callId, String name, Map<String, Object> args, String risk,
                                 boolean ok, String summary, long latencyMs) {
    }

    private final String traceId;
    private final long sessionId;
    private final long userId;
    private final String question;
    private final long startedAt;
    private final long deadlineAt;

    private AgentType agentType = AgentType.SUPERVISOR;
    private int step;
    private int promptTokens;
    private int completionTokens;
    private int costCents;
    private String model = "";
    private String finalAnswer;
    private Long pendingApprovalId;
    private int consecutiveNoProgress;
    private String lastSignature = "";
    private int lastSignatureCount;

    private final List<Citation> citations = new ArrayList<>();
    private final List<ToolInvocation> toolInvocations = new ArrayList<>();
    private final Set<String> infoHashes = new HashSet<>();
    private final List<String> visitedAgents = new ArrayList<>();

    public AgentState(String traceId, long sessionId, long userId, String question, long startedAt,
                      long timeoutMillis) {
        this.traceId = traceId;
        this.sessionId = sessionId;
        this.userId = userId;
        this.question = question;
        this.startedAt = startedAt;
        this.deadlineAt = startedAt + Math.max(1L, timeoutMillis);
    }

    public void beginStep() {
        this.step++;
    }

    public void addUsage(int prompt, int completion, int cost) {
        this.promptTokens += Math.max(0, prompt);
        this.completionTokens += Math.max(0, completion);
        this.costCents += Math.max(0, cost);
    }

    public int totalTokens() {
        return promptTokens + completionTokens;
    }

    /** 记录工具意图（风险分级在调用前就要展示，因此先登记再执行）。 */
    public void recordToolCall(String callId, String name, Map<String, Object> args, String risk) {
        toolInvocations.add(new ToolInvocation(callId, name, args == null ? Map.of() : args, risk,
                false, "", 0L));
        String signature = name + "|" + JsonUtil.toJson(args);
        if (signature.equals(lastSignature)) {
            lastSignatureCount++;
        } else {
            lastSignature = signature;
            lastSignatureCount = 1;
        }
    }

    /** 记录工具结果，返回本轮是否产生新信息（用于「连续 N 步无进展」判定）。 */
    public boolean recordToolResult(boolean ok, String summary, long latencyMs) {
        if (!toolInvocations.isEmpty()) {
            ToolInvocation last = toolInvocations.get(toolInvocations.size() - 1);
            toolInvocations.set(toolInvocations.size() - 1, new ToolInvocation(last.callId(), last.name(),
                    last.args(), last.risk(), ok, summary, latencyMs));
        }
        return noteInfo(summary);
    }

    public boolean noteInfo(String text) {
        String hash = Integer.toHexString(text == null ? 0 : text.hashCode());
        boolean fresh = infoHashes.add(hash);
        if (fresh) {
            consecutiveNoProgress = 0;
        } else {
            consecutiveNoProgress++;
        }
        return fresh;
    }

    public void addCitations(List<Citation> items) {
        if (items == null) {
            return;
        }
        for (Citation citation : items) {
            if (citations.size() >= 12) {
                return;
            }
            boolean exists = citations.stream().anyMatch(existing -> existing.chunkId() == citation.chunkId());
            if (!exists) {
                citations.add(citation);
            }
        }
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put("traceId", traceId);
        map.put("sessionId", sessionId);
        map.put("userId", userId);
        map.put("question", question);
        map.put("agentType", agentType.code());
        map.put("step", step);
        map.put("promptTokens", promptTokens);
        map.put("completionTokens", completionTokens);
        map.put("costCents", costCents);
        map.put("model", model);
        map.put("finalAnswer", finalAnswer);
        map.put("pendingApprovalId", pendingApprovalId);
        map.put("lastSignature", lastSignature);
        map.put("lastSignatureCount", lastSignatureCount);
        map.put("consecutiveNoProgress", consecutiveNoProgress);
        map.put("toolCalls", toolInvocations.size());
        return map;
    }

    public String getTraceId() {
        return traceId;
    }

    public long getSessionId() {
        return sessionId;
    }

    public long getUserId() {
        return userId;
    }

    public String getQuestion() {
        return question;
    }

    public long getStartedAt() {
        return startedAt;
    }

    public long getDeadlineAt() {
        return deadlineAt;
    }

    public AgentType getAgentType() {
        return agentType;
    }

    public void setAgentType(AgentType agentType) {
        this.agentType = agentType;
        if (agentType != null && !visitedAgents.contains(agentType.code())) {
            visitedAgents.add(agentType.code());
        }
    }

    public int getStep() {
        return step;
    }

    public int getPromptTokens() {
        return promptTokens;
    }

    public int getCompletionTokens() {
        return completionTokens;
    }

    public int getCostCents() {
        return costCents;
    }

    public String getModel() {
        return model;
    }

    public void setModel(String model) {
        this.model = model;
    }

    public String getFinalAnswer() {
        return finalAnswer;
    }

    public void setFinalAnswer(String finalAnswer) {
        this.finalAnswer = finalAnswer;
        noteInfo(finalAnswer);
    }

    public boolean hasFinalAnswer() {
        return finalAnswer != null && !finalAnswer.isBlank();
    }

    public Long getPendingApprovalId() {
        return pendingApprovalId;
    }

    public void setPendingApprovalId(Long pendingApprovalId) {
        this.pendingApprovalId = pendingApprovalId;
    }

    public int getConsecutiveNoProgress() {
        return consecutiveNoProgress;
    }

    public int getLastSignatureCount() {
        return lastSignatureCount;
    }

    public List<Citation> getCitations() {
        return citations;
    }

    public List<ToolInvocation> getToolInvocations() {
        return toolInvocations;
    }

    public List<String> getVisitedAgents() {
        return visitedAgents;
    }
}
