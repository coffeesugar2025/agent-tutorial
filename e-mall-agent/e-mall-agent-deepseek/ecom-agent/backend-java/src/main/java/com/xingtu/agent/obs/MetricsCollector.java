package com.xingtu.agent.obs;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.DistributionSummary;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.util.concurrent.atomic.AtomicInteger;

/**
 * Micrometer 指标收集：指标前缀 ecom_agent_。
 *
 * <p>Prometheus 导出时 counter 会自动追加 _total 后缀，因此
 * ecom_agent_requests 在 /metrics 中呈现为 ecom_agent_requests_total。</p>
 */
@Component
public class MetricsCollector {

    private final MeterRegistry registry;
    private final AtomicInteger approvalPending = new AtomicInteger(0);
    private final DistributionSummary stepSummary;

    public MetricsCollector(MeterRegistry registry) {
        this.registry = registry;
        this.stepSummary = DistributionSummary.builder("ecom_agent_step_seconds")
                .description("Agent 单步耗时（秒）")
                .register(registry);
        Gauge.builder("ecom_agent_approval_pending", approvalPending, AtomicInteger::doubleValue)
                .description("待审批任务数")
                .register(registry);
    }

    public void request(String path, String method, int status, long latencyMs) {
        Counter.builder("ecom_agent_requests")
                .tag("path", path)
                .tag("method", method)
                .tag("status", String.valueOf(status))
                .register(registry)
                .increment();
        Timer.builder("ecom_agent_request_seconds")
                .tag("path", path)
                .register(registry)
                .record(java.time.Duration.ofMillis(Math.max(0L, latencyMs)));
    }

    public void llmCall(String provider, String model, int promptTokens, int completionTokens, int costCents) {
        Counter.builder("ecom_agent_llm_calls")
                .tag("provider", provider)
                .tag("model", model)
                .register(registry)
                .increment();
        Counter.builder("ecom_agent_llm_tokens")
                .tag("provider", provider)
                .tag("type", "prompt")
                .register(registry)
                .increment(promptTokens);
        Counter.builder("ecom_agent_llm_tokens")
                .tag("provider", provider)
                .tag("type", "completion")
                .register(registry)
                .increment(completionTokens);
        Counter.builder("ecom_agent_llm_cost_cents")
                .tag("provider", provider)
                .tag("model", model)
                .register(registry)
                .increment(costCents);
    }

    public void llmFailure(String provider, String model) {
        Counter.builder("ecom_agent_llm_failures")
                .tag("provider", provider)
                .tag("model", model)
                .register(registry)
                .increment();
    }

    public void toolCall(String name, String risk, boolean ok, long latencyMs) {
        Counter.builder("ecom_agent_tool_calls")
                .tag("tool", name)
                .tag("risk", risk)
                .tag("result", ok ? "ok" : "error")
                .register(registry)
                .increment();
        Timer.builder("ecom_agent_tool_seconds")
                .tag("tool", name)
                .register(registry)
                .record(java.time.Duration.ofMillis(Math.max(0L, latencyMs)));
    }

    public void agentStep(String agentType, long latencyMs) {
        Counter.builder("ecom_agent_agent_steps")
                .tag("agent", agentType)
                .register(registry)
                .increment();
        stepSummary.record(Math.max(0L, latencyMs) / 1000d);
    }

    public void approvalCreated() {
        approvalPending.incrementAndGet();
    }

    public void approvalDecided() {
        approvalPending.updateAndGet(value -> Math.max(0, value - 1));
    }

    public void setApprovalPending(long value) {
        approvalPending.set((int) Math.max(0L, value));
    }

    public void circuitOpen(String provider) {
        Counter.builder("ecom_agent_circuit_open")
                .tag("provider", provider)
                .register(registry)
                .increment();
    }
}
