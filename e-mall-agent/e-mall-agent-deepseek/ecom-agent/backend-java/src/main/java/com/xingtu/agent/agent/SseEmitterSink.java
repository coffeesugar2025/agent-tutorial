package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：SseEmitter 实现：所有 data 都序列化成紧凑 JSON（单行），按契约的 event 名推送
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * SseEmitter 实现：所有 data 都序列化成紧凑 JSON（单行），按契约的 event 名推送。
 * 客户端断开后置 closed，后续事件静默丢弃。
 */
public class SseEmitterSink implements SseEventSink {

    private static final Logger log = LoggerFactory.getLogger(SseEmitterSink.class);

    private final SseEmitter emitter;
    private final AtomicBoolean closed = new AtomicBoolean(false);

    public SseEmitterSink(SseEmitter emitter) {
        this.emitter = emitter;
        this.emitter.onCompletion(() -> closed.set(true));
        this.emitter.onTimeout(() -> closed.set(true));
        this.emitter.onError(throwable -> closed.set(true));
    }

    public SseEmitter emitter() {
        return emitter;
    }

    @Override
    public void meta(String traceId, long messageId, long sessionId) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("traceId", traceId);
        data.put("messageId", messageId);
        data.put("sessionId", sessionId);
        send("meta", data);
    }

    @Override
    public void agent(String agentType, String reason) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("agentType", agentType);
        data.put("reason", reason);
        send("agent", data);
    }

    @Override
    // ──────── [CAP-01] 交互协议 ────────
    //   本处：SSE 事件发送
    //   域约束：事件名与字段是前后端契约，改动必须同步 docs/03 与前端状态机
    public void delta(String text) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("text", text);
        send("delta", data);
    }

    @Override
    public void toolCall(String callId, String name, Map<String, Object> args, String risk) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("callId", callId);
        data.put("name", name);
        data.put("args", args == null ? Map.of() : args);
        data.put("risk", risk);
        send("tool_call", data);
    }

    @Override
    public void toolResult(String callId, String name, boolean ok, String summary, long latencyMs) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("callId", callId);
        data.put("name", name);
        data.put("ok", ok);
        data.put("summary", summary);
        data.put("latencyMs", latencyMs);
        send("tool_result", data);
    }

    @Override
    public void citation(long docId, long chunkId, String title, String snippet, double score) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("docId", docId);
        data.put("chunkId", chunkId);
        data.put("title", title);
        data.put("snippet", snippet);
        data.put("score", score);
        send("citation", data);
    }

    @Override
    public void approval(long approvalId, String title, Map<String, Object> detail, String risk,
                         String expiresAt) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("approvalId", approvalId);
        data.put("title", title);
        data.put("detail", detail == null ? Map.of() : detail);
        data.put("risk", risk);
        data.put("expiresAt", expiresAt);
        send("approval", data);
    }

    @Override
    public void usage(int promptTokens, int completionTokens, int costCents, String model) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("promptTokens", promptTokens);
        data.put("completionTokens", completionTokens);
        data.put("costCents", costCents);
        data.put("model", model);
        send("usage", data);
    }

    @Override
    public void done(long messageId, String finishReason) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("messageId", messageId);
        data.put("finishReason", finishReason);
        send("done", data);
    }

    @Override
    public void error(int code, String message) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("code", code);
        data.put("message", message);
        send("error", data);
    }

    @Override
    public boolean isClosed() {
        return closed.get();
    }

    /** 心跳：`: ping` 注释行（契约要求空闲时每 15s 一次）。 */
    public void ping() {
        if (closed.get()) {
            return;
        }
        try {
            emitter.send(SseEmitter.event().comment("ping"));
        } catch (IOException | IllegalStateException e) {
            closed.set(true);
        }
    }

    public void complete() {
        if (closed.compareAndSet(false, true)) {
            try {
                emitter.complete();
            } catch (RuntimeException e) {
                log.debug("SSE complete 失败: {}", e.getMessage());
            }
        }
    }

    public void completeWithError(Throwable error) {
        if (closed.compareAndSet(false, true)) {
            try {
                emitter.completeWithError(error);
            } catch (RuntimeException e) {
                log.debug("SSE completeWithError 失败: {}", e.getMessage());
            }
        }
    }

    private void send(String event, Map<String, Object> data) {
        if (closed.get()) {
            return;
        }
        try {
            emitter.send(SseEmitter.event().name(event)
                    .data(JsonUtil.toJson(data), MediaType.TEXT_PLAIN));
        } catch (IOException | IllegalStateException e) {
            closed.set(true);
            log.debug("SSE 发送失败 event={} : {}", event, e.getMessage());
        }
    }
}
