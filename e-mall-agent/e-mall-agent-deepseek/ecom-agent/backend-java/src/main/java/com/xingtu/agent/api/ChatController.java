package com.xingtu.agent.api;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议
// 职责：会话、对话、审批接口（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.agent.AgentRuntime;
import com.xingtu.agent.agent.AgentType;
import com.xingtu.agent.agent.InterruptRegistry;
import com.xingtu.agent.agent.SseEmitterSink;
import com.xingtu.agent.api.dto.ChatDtos;
import com.xingtu.agent.common.ApiResponse;
import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.Ids;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.common.TraceContext;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.hitl.ApprovalService;
import com.xingtu.agent.infra.repo.ApprovalRepository;
import com.xingtu.agent.infra.repo.MessageRepository;
import com.xingtu.agent.infra.repo.SessionRepository;
import com.xingtu.agent.rag.Citation;
import com.xingtu.agent.security.RateLimiter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Executor;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;

/**
 * 会话、对话、审批接口（docs/03-API契约.md 第 2 节）。
 *
 * <p>SSE 事件名与 data 结构由 {@link SseEmitterSink} 统一产出，与契约逐字一致：
 * meta / agent / delta / tool_call / tool_result / citation / approval / usage / done / error，
 * 空闲时每 15s 发送 `: ping` 注释行。</p>
 */
@RestController
@RequestMapping("/api/v1/chat")
public class ChatController {

    private static final Logger log = LoggerFactory.getLogger(ChatController.class);
    private static final int MAX_MESSAGE_LIMIT = 200;
    private static final int HEARTBEAT_SECONDS = 15;
    private static final int APPROVAL_LIST_LIMIT = 50;

    private final AgentRuntime agentRuntime;
    private final SessionRepository sessionRepository;
    private final MessageRepository messageRepository;
    private final ApprovalService approvalService;
    private final InterruptRegistry interruptRegistry;
    private final RateLimiter rateLimiter;
    private final AppProperties props;
    private final Executor agentExecutor;
    private final ScheduledExecutorService sseScheduler;

    public ChatController(AgentRuntime agentRuntime, SessionRepository sessionRepository,
                          MessageRepository messageRepository, ApprovalService approvalService,
                          InterruptRegistry interruptRegistry, RateLimiter rateLimiter,
                          AppProperties props, @Qualifier("agentExecutor") Executor agentExecutor,
                          @Qualifier("sseScheduler") ScheduledExecutorService sseScheduler) {
        this.agentRuntime = agentRuntime;
        this.sessionRepository = sessionRepository;
        this.messageRepository = messageRepository;
        this.approvalService = approvalService;
        this.interruptRegistry = interruptRegistry;
        this.rateLimiter = rateLimiter;
        this.props = props;
        this.agentExecutor = agentExecutor;
        this.sseScheduler = sseScheduler;
    }

    @PostMapping("/sessions")
    public ApiResponse<ChatDtos.SessionVO> createSession(
            @RequestBody(required = false) ChatDtos.SessionCreateReq req) {
        long userId = TraceContext.userId();
        String title = req == null || req.title() == null || req.title().isBlank()
                ? "新会话" : trimTitle(req.title());
        long sessionId = sessionRepository.insert(userId, title, AgentType.SUPERVISOR.code());
        SessionRepository.SessionRow row = sessionRepository.findById(sessionId);
        return ApiResponse.ok(row == null
                ? new ChatDtos.SessionVO(sessionId, title, AgentType.SUPERVISOR.code(), "ACTIVE", null, null)
                : toSessionVO(row));
    }

    @GetMapping("/sessions")
    public ApiResponse<List<ChatDtos.SessionVO>> listSessions() {
        List<ChatDtos.SessionVO> items = new ArrayList<>();
        for (SessionRepository.SessionRow row : sessionRepository.listByUser(TraceContext.userId(), 50)) {
            items.add(toSessionVO(row));
        }
        return ApiResponse.ok(items);
    }

    @GetMapping("/sessions/{id}")
    public ApiResponse<ChatDtos.SessionVO> getSession(@PathVariable("id") long sessionId) {
        return ApiResponse.ok(toSessionVO(requireOwnSession(sessionId)));
    }

    @DeleteMapping("/sessions/{id}")
    public ApiResponse<Void> deleteSession(@PathVariable("id") long sessionId) {
        requireOwnSession(sessionId);
        if (!sessionRepository.softDelete(sessionId, TraceContext.userId())) {
            throw BizException.notFound("会话不存在: " + sessionId);
        }
        return ApiResponse.ok();
    }

    @GetMapping("/sessions/{id}/messages")
    public ApiResponse<List<ChatDtos.MessageVO>> messages(
            @PathVariable("id") long sessionId,
            @RequestParam(value = "limit", defaultValue = "50") int limit) {
        requireOwnSession(sessionId);
        int normalizedLimit = Math.max(1, Math.min(limit, MAX_MESSAGE_LIMIT));
        List<ChatDtos.MessageVO> items = new ArrayList<>();
        for (MessageRepository.MessageRow row : messageRepository.list(sessionId, normalizedLimit)) {
            items.add(toMessageVO(row));
        }
        return ApiResponse.ok(items);
    }

    /**
     * 核心流式接口：立即返回 SseEmitter，Agent 在 agentExecutor 中执行。
     * 参数校验/权限错误在返回 emitter 之前抛出，由 GlobalExceptionHandler 输出标准 JSON 信封。
     */
    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter stream(@RequestBody(required = false) ChatDtos.ChatStreamReq req) {
        if (req == null || req.sessionId() <= 0) {
            throw BizException.validation("sessionId 不合法");
        }
        String message = req.message() == null ? "" : req.message().trim();
        if (message.isEmpty()) {
            throw BizException.validation("message 不能为空");
        }
        long userId = TraceContext.userId();
        SessionRepository.SessionRow session = requireOwnSession(req.sessionId());
        rateLimiter.check(userId, "chat");

        final String traceId = TraceContext.traceId() == null || TraceContext.traceId().isBlank()
                ? Ids.newTraceId() : TraceContext.traceId();
        final String username = TraceContext.username();
        final List<String> roles = TraceContext.roles();
        final long sessionId = session.id();
        final String clientMsgId = req.clientMsgId();

        long timeoutMillis = Math.max(30_000L, props.getAgent().getTaskTimeoutSeconds() * 1000L + 30_000L);
        SseEmitter emitter = new SseEmitter(timeoutMillis);
        SseEmitterSink sink = new SseEmitterSink(emitter);
        ScheduledFuture<?> heartbeat = sseScheduler.scheduleAtFixedRate(sink::ping, HEARTBEAT_SECONDS,
                HEARTBEAT_SECONDS, TimeUnit.SECONDS);
        AgentRuntime.AgentRunInput input = new AgentRuntime.AgentRunInput(userId, roles, sessionId,
                message, clientMsgId, traceId);

        try {
            agentExecutor.execute(() -> {
                TraceContext.setTraceId(traceId);
                TraceContext.setIdentity(userId, username, roles);
                try {
                    agentRuntime.run(input, sink);
                } catch (RuntimeException e) {
                    log.error("SSE 会话执行失败 sessionId={} traceId={}", sessionId, traceId, e);
                    sink.error(50000, "服务内部错误");
                } finally {
                    heartbeat.cancel(false);
                    sink.complete();
                    TraceContext.clear();
                }
            });
        } catch (RuntimeException e) {
            heartbeat.cancel(false);
            log.error("提交 SSE 任务失败 sessionId={} traceId={}", sessionId, traceId, e);
            sink.error(50000, "服务繁忙，请稍后重试");
            sink.complete();
        }
        return emitter;
    }

    @PostMapping("/sessions/{id}/interrupt")
    public ApiResponse<ChatDtos.InterruptVO> interrupt(@PathVariable("id") long sessionId) {
        requireOwnSession(sessionId);
        interruptRegistry.interrupt(sessionId);
        return ApiResponse.ok(new ChatDtos.InterruptVO(true));
    }

    @GetMapping("/approvals")
    public ApiResponse<List<ChatDtos.ApprovalVO>> approvals(
            @RequestParam(value = "status", required = false) String status) {
        List<ChatDtos.ApprovalVO> items = new ArrayList<>();
        for (ApprovalRepository.ApprovalRow row : approvalService.list(TraceContext.userId(), status,
                APPROVAL_LIST_LIMIT)) {
            items.add(toApprovalVO(row));
        }
        return ApiResponse.ok(items);
    }

    @PostMapping("/approvals/{approvalId}")
    public ApiResponse<ChatDtos.ApprovalDecisionVO> decide(@PathVariable("approvalId") long approvalId,
                                                           @RequestBody(required = false) ChatDtos.ApprovalDecisionReq req) {
        String decision = req == null ? null : req.decision();
        String comment = req == null ? null : req.comment();
        ApprovalService.DecisionResult result = approvalService.decide(TraceContext.userId(), approvalId,
                decision, comment, new java.util.LinkedHashSet<>(TraceContext.roles()));
        return ApiResponse.ok(new ChatDtos.ApprovalDecisionVO(result.id(), result.status(),
                result.result()));
    }

    private SessionRepository.SessionRow requireOwnSession(long sessionId) {
        SessionRepository.SessionRow row = sessionRepository.findById(sessionId);
        if (row == null || row.userId() != TraceContext.userId()) {
            throw BizException.notFound("会话不存在或无权访问");
        }
        return row;
    }

    private ChatDtos.SessionVO toSessionVO(SessionRepository.SessionRow row) {
        return new ChatDtos.SessionVO(row.id(), row.title(), row.agentType(), row.status(),
                JsonUtil.formatTime(row.lastMessageAt()), JsonUtil.formatTime(row.createdAt()));
    }

    private ChatDtos.MessageVO toMessageVO(MessageRepository.MessageRow row) {
        List<ChatDtos.ToolCallVO> toolCalls = JsonUtil.parseList(row.toolCalls(), ChatDtos.ToolCallVO.class);
        List<ChatDtos.CitationVO> citations = new ArrayList<>();
        for (Citation citation : JsonUtil.parseList(row.citations(), Citation.class)) {
            citations.add(new ChatDtos.CitationVO(citation.docId(), citation.chunkId(), citation.title(),
                    citation.snippet(), citation.score()));
        }
        return new ChatDtos.MessageVO(row.id(), row.role(), row.content(), row.agentType(), toolCalls,
                citations, row.tokenIn(), row.tokenOut(), row.costCents(),
                JsonUtil.formatTime(row.createdAt()));
    }

    private ChatDtos.ApprovalVO toApprovalVO(ApprovalRepository.ApprovalRow row) {
        return new ChatDtos.ApprovalVO(row.id(), row.sessionId(), row.actionType(), row.title(),
                JsonUtil.parseMap(row.detailJson()), row.risk(), row.status(),
                JsonUtil.formatTime(row.createdAt()), JsonUtil.formatTime(row.expiresAt()));
    }

    private String trimTitle(String title) {
        String trimmed = title.trim();
        return trimmed.length() <= 200 ? trimmed : trimmed.substring(0, 200);
    }
}
