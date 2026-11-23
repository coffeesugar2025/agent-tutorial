package com.xingtu.agent.api.dto;

import java.util.List;
import java.util.Map;

/**
 * 运营、可观测与评测 DTO（docs/03-API契约.md 第 6 节）。
 */
public final class AdminDtos {

    private AdminDtos() {
    }

    /** 工具调用排行项。 */
    public record TopToolVO(String name, long count) {
    }

    /** 趋势点（按天）。 */
    public record TrendPointVO(String date, long sessions, long costCents) {
    }

    /** GET /api/v1/admin/overview 响应 data。 */
    public record OverviewVO(long totalSessions, long totalMessages, double successRate,
                             long avgLatencyMs, long p95LatencyMs, long totalCostCents,
                             double costPerSuccessCents, long approvalPending, double toolErrorRate,
                             List<TopToolVO> topTools, List<TrendPointVO> trend) {
    }

    /** 链路列表项 / 详情里的 trace 对象。 */
    public record TraceVO(String traceId, long sessionId, String agentType, String status,
                          int totalLatencyMs, int totalCostCents, int stepCount) {
    }

    /** 链路 span。 */
    public record SpanVO(String spanId, String parentSpanId, String name, String spanType, int seq,
                         Map<String, Object> input, Map<String, Object> output, int latencyMs,
                         String status) {
    }

    /** GET /api/v1/admin/traces/{traceId} 响应 data。 */
    public record TraceDetailVO(TraceVO trace, List<SpanVO> spans, boolean replayable) {
    }

    /** 按模型成本。 */
    public record ModelCostVO(String model, long calls, long costCents) {
    }

    /** 按供应商成本。 */
    public record ProviderCostVO(String provider, long costCents) {
    }

    /** 按天成本。 */
    public record DailyCostVO(String date, long calls, long costCents) {
    }

    /** GET /api/v1/admin/costs 响应 data。 */
    public record CostsVO(long total, List<ModelCostVO> byModel, List<ProviderCostVO> byProvider,
                          List<DailyCostVO> daily) {
    }

    /** GET /api/v1/admin/models 列表项。 */
    public record ModelStatusVO(String provider, String model, String role, boolean healthy,
                                String circuit, long avgLatencyMs, long calls) {
    }

    /** POST /api/v1/admin/evals/run 请求体。 */
    public record EvalRunReq(String suite, Integer repeat) {
    }

    /** 评测启动响应 data。 */
    public record EvalRunStartVO(long runId, String status) {
    }

    /** 评测用例结果。 */
    public record EvalCaseVO(String caseId, String question, String expected, String actual,
                             boolean passed, double score) {
    }

    /** 评测批次视图（列表接口 cases 为空）。 */
    public record EvalRunVO(long id, String suite, String status, int total, int passed,
                            double passRate, double passK, int avgCostCents, int avgLatencyMs,
                            List<EvalCaseVO> cases) {
    }
}
