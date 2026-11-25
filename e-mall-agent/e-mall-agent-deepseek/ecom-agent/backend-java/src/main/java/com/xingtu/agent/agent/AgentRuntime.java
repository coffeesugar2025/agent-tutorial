package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：Agent 主循环（手写 ReAct）：路由 -> 组装上下文 -> 调模型 -> 解析工具调用 -> 执行/挂起审批 
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.common.TokenEstimator;
import com.xingtu.agent.hitl.ApprovalRequiredException;
import com.xingtu.agent.infra.repo.MessageRepository;
import com.xingtu.agent.infra.repo.SessionRepository;
import com.xingtu.agent.llm.LlmProvider;
import com.xingtu.agent.obs.Tracer;
import com.xingtu.agent.rag.Citation;
import com.xingtu.agent.rag.HybridRetriever;
import com.xingtu.agent.tool.ToolContext;
import com.xingtu.agent.tool.ToolRegistry;
import com.xingtu.agent.tool.ToolResult;
import com.xingtu.agent.tool.ToolRisk;
import lombok.extern.slf4j.Slf4j;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Agent 主循环（手写 ReAct）：路由 -> 组装上下文 -> 调模型 -> 解析工具调用 -> 执行/挂起审批 -> 终止判定。
 *
 * <p>7 条终止条件由 {@link TerminationPolicy} 统一判定；IRREVERSIBLE 工具不会直接执行，
 * 而是创建 approval_task 并中断（SSE 发 approval + done:approval_required）。</p>
 */
@Component
@Slf4j
public class AgentRuntime {

    private static final Logger log = LoggerFactory.getLogger(AgentRuntime.class);
    private static final int DELTA_CHUNK_SIZE = 24;

    public record AgentRunInput(long userId, List<String> roles, long sessionId, String question,
                                String clientMsgId, String traceId) {
    }

    public record AgentResult(long messageId, String finishReason, int promptTokens, int completionTokens,
                              int costCents, String model, String answer, Long approvalId, int steps,
                              String traceId) {
    }

    private final AgentDeps deps;
    private final TerminationPolicy policy;
    private final PromptBuilder promptBuilder = new PromptBuilder();
    private final ToolCallParser toolCallParser = new ToolCallParser();

    public AgentRuntime(AgentDeps deps) {
        this.deps = deps;
        this.policy = TerminationPolicy.from(deps.props());
    }

    // ──────── [CAP-03] 运行时循环 ────────
    //   本处：主循环（判终止→调模型→执行工具）
    //   域约束：判定顺序固定为 超时→步数→预算→循环→无进展，同时命中也必须稳定返回同一个原因
    public AgentResult run(AgentRunInput input, SseEventSink sink) {
        log.info("AgentResult run start -----------------------");
        long startedAt = System.currentTimeMillis();
        AgentState state = new AgentState(input.traceId(), input.sessionId(), input.userId(),
                input.question(), startedAt, deps.props().getAgent().getTaskTimeoutSeconds() * 1000L);
        sink.meta(input.traceId(), 0L, input.sessionId());
        deps.tracer().startTrace(input.traceId(), input.sessionId(), input.userId(), null, input.question());

        String finishReason = "error";
        boolean errorSent = false;
        String answer = "";
        Long approvalId = null;
        long messageId = 0L;

        try {
            SessionRepository.SessionRow session = deps.sessionRepository().findById(input.sessionId());
            if (session == null || session.userId() != input.userId()) {
                throw BizException.notFound("会话不存在或无权访问");
            }
            deps.messageRepository().insert(new MessageRepository.MessageInsert(input.sessionId(), "user",
                    input.question(), null, null, null, 0, 0, 0, input.traceId()));
            deps.sessionRepository().touch(input.sessionId(), LocalDateTime.now());

            SupervisorAgent.Route route = deps.agentRegistry().supervisor().route(input.question());
            state.setAgentType(route.type());
            sink.agent(route.type().code(), route.reason());
            deps.sessionRepository().updateAgentType(input.sessionId(), route.type().code());
            Agent agent = deps.agentRegistry().get(route.type());
            String toolCatalog = deps.toolRegistry().catalog(route.type().code());
            String systemPrompt = promptBuilder.systemPrompt(agent);

            List<LlmProvider.Message> history = deps.sessionMemory().window(input.sessionId());
            if (!history.isEmpty()) {
                history = history.subList(0, history.size() - 1);
            }
            HybridRetriever.Result retrieval = retrieve(input.question());
            state.addCitations(retrieval.citations());
            emitCitations(sink, retrieval.citations());
            String contextText = deps.contextAssembler().assemble(retrieval.citations(), 3000).contextText();
            String profile = safeProfile(input.userId());
            String memories = safeMemories(input.userId(), input.question());

            while (true) {
                if (deps.interrupts().isInterrupted(input.sessionId())) {
                    finishReason = "interrupted";
                    answer = "已按你的要求中断本轮回答。";
                    state.setFinalAnswer(answer);
                    emitDeltas(sink, answer);
                    break;
                }
                TerminationPolicy.Verdict verdict = policy.check(state, System.currentTimeMillis());
                if (verdict.stop()) {
                    finishReason = policy.finishReason(verdict.reason());
                    answer = state.hasFinalAnswer() ? state.getFinalAnswer()
                            : terminatedAnswer(verdict.reason(), state);
                    if (!state.hasFinalAnswer()) {
                        emitDeltas(sink, answer);
                    }
                    break;
                }
                state.beginStep();
                String userPrompt = promptBuilder.userPrompt(state, agent, toolCatalog, session.summary(),
                        history, contextText, profile, memories);
                LlmProvider.Result llm;
                long stepStarted = System.currentTimeMillis();
                Tracer.SpanHandle llmSpan = deps.tracer().span(input.traceId(), "llm.chat", "LLM",
                        state.getStep(), Map.of("step", state.getStep(), "agent", agent.type().code()));
                try {
                    llm = deps.modelRouter().chat(buildRequest(systemPrompt, userPrompt));
                    deps.tracer().end(llmSpan, Map.of("provider", llm.provider(), "model", llm.model(),
                            "tokens", llm.totalTokens()), "OK", null);
                } catch (RuntimeException e) {
                    deps.tracer().endError(llmSpan, e);
                    answer = degradationAnswer();
                    emitDeltas(sink, answer);
                    state.addUsage(TokenEstimator.estimate(userPrompt), TokenEstimator.estimate(answer), 0);
                    approvalId = escalateOnFailure(input, state, e.getMessage());
                    finishReason = "error";
                    break;
                }

                int cost = deps.costCalculator().costCents(llm.model(), llm.promptTokens(),
                        llm.completionTokens());
                state.addUsage(llm.promptTokens(), llm.completionTokens(), cost);
                state.setModel(llm.model());
                deps.metrics().agentStep(agent.type().code(), System.currentTimeMillis() - stepStarted);

                Optional<ToolCallParser.ToolCall> maybeCall = toolCallParser.parse(llm.text());
                if (maybeCall.isEmpty()) {
                    answer = llm.text() == null ? "" : llm.text().trim();
                    state.setFinalAnswer(answer);
                    emitDeltas(sink, answer);
                    finishReason = "stop";
                    break;
                }
                ToolCallParser.ToolCall call = maybeCall.get();
                String callId = "c" + state.getStep();
                Optional<ToolRegistry.Definition> definition = deps.toolRegistry().find(call.name());
                if (definition.isEmpty()) {
                    state.recordToolCall(callId, call.name(), call.args(), ToolRisk.READ.name());
                    sink.toolCall(callId, call.name(), call.args(), ToolRisk.READ.name());
                    sink.toolResult(callId, call.name(), false, "未注册的工具: " + call.name(), 0L);
                    state.recordToolResult(false, "未注册的工具: " + call.name(), 0L);
                    checkpoint(state);
                    continue;
                }
                ToolRegistry.Definition tool = definition.get();
                if (tool.risk() == ToolRisk.IRREVERSIBLE) {
                    state.recordToolCall(callId, call.name(), call.args(), tool.risk().name());
                    ApprovalRequiredException required = requireApproval(input, tool, call, state);
                    approvalId = required.getApprovalId();
                    state.setPendingApprovalId(approvalId);
                    sink.approval(required.getApprovalId(), required.getTitle(), required.getDetail(),
                            required.getRisk(), required.getExpiresAt());
                    answer = "本次操作（" + required.getTitle() + "）属于不可逆动作，已提交人工审批（审批单 #"
                            + required.getApprovalId() + "）。审批通过后系统会自动执行，"
                            + "你可以在「审批」列表中查看或处理。";
                    state.setFinalAnswer(answer);
                    emitDeltas(sink, answer);
                    finishReason = "approval_required";
                    break;
                }

                state.recordToolCall(callId, call.name(), call.args(), tool.risk().name());
                sink.toolCall(callId, call.name(), call.args(), tool.risk().name());
                ToolContext context = new ToolContext(input.userId(), input.sessionId(), input.traceId(),
                        input.roles(), input.question());
                Tracer.SpanHandle toolSpan = deps.tracer().span(input.traceId(), "tool." + call.name(), "TOOL",
                        state.getStep(), call.args());
                ToolResult result = deps.toolRegistry().execute(call.name(), call.args(), context);
                deps.tracer().end(toolSpan, Map.of("ok", result.ok(), "summary", result.summary()),
                        result.ok() ? "OK" : "ERROR", result.ok() ? null : result.summary());
                deps.metrics().toolCall(call.name(), tool.risk().name(), result.ok(), result.latencyMs());
                sink.toolResult(callId, call.name(), result.ok(), result.summary(), result.latencyMs());
                if (!result.citations().isEmpty()) {
                    state.addCitations(result.citations());
                    emitCitations(sink, result.citations());
                }
                state.recordToolResult(result.ok(), result.summary(), result.latencyMs());
                checkpoint(state);
            }
        } catch (BizException e) {
            errorSent = true;
            finishReason = "error";
            sink.error(e.getCode(), e.getMessage());
        } catch (RuntimeException e) {
            errorSent = true;
            finishReason = "error";
            log.error("Agent 执行异常 traceId={} sessionId={}", input.traceId(), input.sessionId(), e);
            sink.error(50000, "服务内部错误");
        } finally {
            try {
                messageId = persistAssistantMessage(input, state, answer);
            } catch (RuntimeException e) {
                log.warn("持久化 assistant 消息失败: {}", e.getMessage());
            }
            sink.usage(state.getPromptTokens(), state.getCompletionTokens(), state.getCostCents(),
                    state.getModel());
            if (!errorSent) {
                sink.done(messageId, finishReason);
            }
            deps.tracer().finishTrace(input.traceId(), traceStatus(finishReason),
                    System.currentTimeMillis() - startedAt, state.getCostCents(), state.getStep(), answer);
            deps.interrupts().clear(input.sessionId());
            log.info("AgentResult run end -----------------------");
        }
        return new AgentResult(messageId, finishReason, state.getPromptTokens(), state.getCompletionTokens(),
                state.getCostCents(), state.getModel(), answer, approvalId, state.getStep(), input.traceId());
    }

    private LlmProvider.Request buildRequest(String systemPrompt, String userPrompt) {
        List<LlmProvider.Message> messages = new ArrayList<>();
        messages.add(LlmProvider.Message.system(systemPrompt));
        messages.add(LlmProvider.Message.user(userPrompt));
        return new LlmProvider.Request(messages, deps.props().getLlm().getTemperature(),
                deps.props().getLlm().getMaxTokens());
    }

    private HybridRetriever.Result retrieve(String question) {
        try {
            return deps.retriever().retrieve(question, deps.props().getRag().getRerankTopN(), null, "hybrid");
        } catch (RuntimeException e) {
            log.warn("知识检索失败，跳过 RAG: {}", e.getMessage());
            return new HybridRetriever.Result(List.of(), List.of(),
                    new HybridRetriever.Debug(0, 0, 0, 0L, "failed"));
        }
    }

    private String safeProfile(long userId) {
        try {
            return deps.userProfileService().render(userId);
        } catch (RuntimeException e) {
            return "";
        }
    }

    private String safeMemories(long userId, String question) {
        try {
            return deps.longTermMemory().render(userId, question, 3);
        } catch (RuntimeException e) {
            return "";
        }
    }

    private Long escalateOnFailure(AgentRunInput input, AgentState state, String error) {
        try {
            Map<String, Object> detail = new LinkedHashMap<>();
            detail.put("reason", "模型全部不可用");
            detail.put("error", error);
            detail.put("question", input.question());
            var row = deps.approvalService().create(input.sessionId(), null, input.userId(),
                    com.xingtu.agent.hitl.ApprovalService.ACTION_ESCALATE, "模型降级转人工", detail, "WRITE");
            state.setPendingApprovalId(row.id());
            return row.id();
        } catch (RuntimeException e) {
            log.warn("降级转人工失败: {}", e.getMessage());
            return null;
        }
    }

    private ApprovalRequiredException requireApproval(AgentRunInput input, ToolRegistry.Definition tool,
                                                      ToolCallParser.ToolCall call, AgentState state) {
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("tool", call.name());
        detail.put("args", call.args());
        if ("create_refund_request".equals(call.name())) {
            String orderNo = ToolContext.str(call.args(), "orderNo", "LATEST");
            detail.put("orderNo", orderNo);
            detail.put("reason", ToolContext.str(call.args(), "reason", "用户申请退款"));
            Object amount = call.args().get("amount");
            if (amount != null) {
                detail.put("amount", amount);
            }
            detail.put("idempotencyKey", ToolContext.str(call.args(), "idempotencyKey",
                    "refund:" + input.userId() + ":" + orderNo));
        }
        String actionType = "create_refund_request".equals(call.name())
                ? com.xingtu.agent.hitl.ApprovalService.ACTION_CREATE_REFUND
                : call.name().toUpperCase();
        String title = "create_refund_request".equals(call.name()) ? "退款审批" : "高风险操作审批";
        return deps.approvalService().require(input.sessionId(), null, input.userId(), actionType, title,
                detail, ToolRisk.IRREVERSIBLE.name());
    }

    private void emitCitations(SseEventSink sink, List<Citation> citations) {
        for (Citation citation : citations) {
            sink.citation(citation.docId(), citation.chunkId(), citation.title(), citation.snippet(),
                    citation.score());
        }
    }

    private void emitDeltas(SseEventSink sink, String text) {
        if (text == null || text.isEmpty()) {
            return;
        }
        int index = 0;
        while (index < text.length()) {
            int end = Math.min(text.length(), index + DELTA_CHUNK_SIZE);
            sink.delta(text.substring(index, end));
            index = end;
        }
    }

    private long persistAssistantMessage(AgentRunInput input, AgentState state, String answer) {
        if (answer == null || answer.isBlank()) {
            return 0L;
        }
        List<Map<String, Object>> toolCalls = new ArrayList<>();
        for (AgentState.ToolInvocation invocation : state.getToolInvocations()) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("callId", invocation.callId());
            item.put("name", invocation.name());
            item.put("args", invocation.args());
            item.put("ok", invocation.ok());
            item.put("summary", invocation.summary());
            item.put("risk", invocation.risk());
            item.put("latencyMs", invocation.latencyMs());
            toolCalls.add(item);
        }
        long id = deps.messageRepository().insert(new MessageRepository.MessageInsert(input.sessionId(),
                "assistant", answer, state.getAgentType().code(),
                toolCalls.isEmpty() ? null : JsonUtil.toJson(toolCalls),
                state.getCitations().isEmpty() ? null : JsonUtil.toJson(state.getCitations()),
                state.getPromptTokens(), state.getCompletionTokens(), state.getCostCents(), input.traceId()));
        deps.sessionRepository().touch(input.sessionId(), LocalDateTime.now());
        return id;
    }

    private void checkpoint(AgentState state) {
        if (!deps.props().getAgent().isCheckpointEnabled()) {
            return;
        }
        try {
            deps.checkpointRepository().save(state.getSessionId(), state.getTraceId(), state.getStep(),
                    JsonUtil.toJson(state.snapshot()));
        } catch (RuntimeException e) {
            log.debug("写检查点失败: {}", e.getMessage());
        }
    }

    private String terminatedAnswer(TerminationPolicy.Reason reason, AgentState state) {
        switch (reason) {
            case MAX_STEPS:
                return "已经达到本轮可执行的最大步数，我先给出阶段性结论："
                        + lastToolSummary(state) + "。可以继续追问更具体的问题。";
            case TOKEN_BUDGET:
                return "本轮对话的 token 预算已用尽，建议开启新会话继续深入。";
            case TIMEOUT:
                return "本轮处理超时，已停止继续调用工具。可以稍后重试或补充更精确的信息。";
            case NO_PROGRESS:
                return "连续几步没有获得新信息，我先停止以免浪费资源。建议补充订单号或更具体的条件。";
            case LOOP_DETECTED:
                return "检测到重复调用同一工具，已自动停止。请换个问法或补充关键信息。";
            default:
                return "暂时无法继续处理，请补充信息后重试。";
        }
    }

    private String lastToolSummary(AgentState state) {
        List<AgentState.ToolInvocation> invocations = state.getToolInvocations();
        if (invocations.isEmpty()) {
            return "暂无可用的工具结论";
        }
        AgentState.ToolInvocation last = invocations.get(invocations.size() - 1);
        return last.summary() == null || last.summary().isBlank() ? "工具已执行" : last.summary();
    }

    private String degradationAnswer() {
        return "抱歉，智能助手暂时不可用（模型服务降级中）。已为你转接人工客服，"
                + "你也可以稍后重试；订单、物流等查询能力不受影响。";
    }

    private String traceStatus(String finishReason) {
        if ("stop".equals(finishReason)) {
            return "SUCCESS";
        }
        if ("error".equals(finishReason)) {
            return "FAILED";
        }
        return "INTERRUPTED";
    }
}
