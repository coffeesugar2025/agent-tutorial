package com.xingtu.agent.obs;

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.infra.repo.SpanRepository;
import com.xingtu.agent.infra.repo.TraceRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 链路追踪：agent_trace 为根节点，agent_span 记录 LLM / TOOL / RETRIEVAL / AGENT / GUARDRAIL 节点。
 * 落库失败只告警，不影响业务。
 */
@Component
public class Tracer {

    private static final Logger log = LoggerFactory.getLogger(Tracer.class);

    private final TraceRepository traceRepository;
    private final SpanRepository spanRepository;
    private final ThreadLocal<String> currentSpan = new ThreadLocal<>();

    public Tracer(TraceRepository traceRepository, SpanRepository spanRepository) {
        this.traceRepository = traceRepository;
        this.spanRepository = spanRepository;
    }

    /** 已开始的 span 句柄。 */
    public record SpanHandle(String traceId, String spanId, String parentSpanId, String name, String type,
                             int seq, Map<String, Object> input, long startedAt) {
    }

    public void startTrace(String traceId, long sessionId, long userId, String agentType, String question) {
        try {
            traceRepository.insert(traceId, sessionId, userId, agentType, question);
        } catch (RuntimeException e) {
            log.warn("写入 agent_trace 失败: {}", e.getMessage());
        }
    }

    public SpanHandle span(String traceId, String name, String type, int seq, Object input) {
        String spanId = com.xingtu.agent.common.Ids.spanId();
        String parent = currentSpan.get();
        currentSpan.set(spanId);
        Map<String, Object> inputMap = JsonUtil.toMap(input);
        return new SpanHandle(traceId, spanId, parent, name, type, seq, inputMap,
                System.currentTimeMillis());
    }

    public void end(SpanHandle handle, Object output, String status, String error) {
        if (handle == null) {
            return;
        }
        long latency = System.currentTimeMillis() - handle.startedAt();
        currentSpan.remove();
        try {
            spanRepository.insert(handle.traceId(), handle.spanId(), handle.parentSpanId(), handle.name(),
                    handle.type(), handle.seq(), JsonUtil.toJson(handle.input()),
                    JsonUtil.toJsonOrNull(output), (int) latency, status == null ? "OK" : status, error);
        } catch (RuntimeException e) {
            log.warn("写入 agent_span 失败: {}", e.getMessage());
        }
    }

    public void endError(SpanHandle handle, Throwable error) {
        end(handle, null, "ERROR", error == null ? null : String.valueOf(error.getMessage()));
    }

    public void finishTrace(String traceId, String status, long latencyMs, int costCents, int stepCount,
                            String answer) {
        try {
            traceRepository.finish(traceId, status, (int) latencyMs, costCents, stepCount, answer);
        } catch (RuntimeException e) {
            log.warn("更新 agent_trace 失败: {}", e.getMessage());
        }
    }

    public String currentSpanId() {
        return currentSpan.get();
    }

    public void clear() {
        currentSpan.remove();
    }
}
