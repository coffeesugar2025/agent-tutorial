package com.xingtu.agent.llm;

import com.xingtu.agent.common.TraceContext;
import com.xingtu.agent.infra.repo.LlmCallRepository;
import com.xingtu.agent.obs.MetricsCollector;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 每次模型调用都落 llm_call（成本、token、时延），并打点 micrometer。
 * 落库失败不影响主流程（成本统计是旁路）。
 */
@Component
public class LlmCallRecorder {

    private static final Logger log = LoggerFactory.getLogger(LlmCallRecorder.class);

    private final LlmCallRepository repository;
    private final MetricsCollector metrics;

    public LlmCallRecorder(LlmCallRepository repository, MetricsCollector metrics) {
        this.repository = repository;
        this.metrics = metrics;
    }

    public void record(String provider, String model, int promptTokens, int completionTokens, int costCents,
                       long latencyMs, String status) {
        metrics.llmCall(provider, model, promptTokens, completionTokens, costCents);
        try {
            repository.insert(TraceContext.traceId(), null, provider, model, promptTokens, completionTokens,
                    0, costCents, (int) latencyMs, status);
        } catch (RuntimeException e) {
            log.warn("写入 llm_call 失败 provider={} model={} : {}", provider, model, e.getMessage());
        }
    }

    public void recordFailure(String provider, String model, long latencyMs, String error) {
        metrics.llmFailure(provider, model);
        try {
            repository.insert(TraceContext.traceId(), null, provider, model, 0, 0, 0, 0,
                    (int) latencyMs, "ERROR:" + abbreviate(error));
        } catch (RuntimeException e) {
            log.warn("写入 llm_call(失败) 失败: {}", e.getMessage());
        }
    }

    private String abbreviate(String text) {
        if (text == null) {
            return "";
        }
        return text.length() <= 120 ? text : text.substring(0, 120);
    }
}
