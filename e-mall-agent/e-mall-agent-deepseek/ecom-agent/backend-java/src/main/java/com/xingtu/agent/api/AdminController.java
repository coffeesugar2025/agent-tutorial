package com.xingtu.agent.api;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议
// 职责：运营与可观测接口（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.api.dto.AdminDtos;
import com.xingtu.agent.common.ApiResponse;
import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.eval.EvalRunner;
import com.xingtu.agent.infra.RabbitPublisher;
import com.xingtu.agent.infra.repo.ApprovalRepository;
import com.xingtu.agent.infra.repo.EvalRepository;
import com.xingtu.agent.infra.repo.LlmCallRepository;
import com.xingtu.agent.infra.repo.MessageRepository;
import com.xingtu.agent.infra.repo.SessionRepository;
import com.xingtu.agent.infra.repo.SpanRepository;
import com.xingtu.agent.infra.repo.StatsRepository;
import com.xingtu.agent.infra.repo.TraceRepository;
import com.xingtu.agent.llm.ModelRouter;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.Executor;

/**
 * 运营与可观测接口（docs/03-API契约.md 第 6 节），RBAC 由 RbacInterceptor 统一拦截（ADMIN）。
 */
@RestController
@RequestMapping("/api/v1/admin")
public class AdminController {

    private static final int MAX_TRACE_LIMIT = 200;
    private static final int MAX_EVAL_REPEAT = 5;

    private final SessionRepository sessionRepository;
    private final MessageRepository messageRepository;
    private final TraceRepository traceRepository;
    private final SpanRepository spanRepository;
    private final LlmCallRepository llmCallRepository;
    private final ApprovalRepository approvalRepository;
    private final EvalRepository evalRepository;
    private final StatsRepository statsRepository;
    private final ModelRouter modelRouter;
    private final EvalRunner evalRunner;
    private final RabbitPublisher rabbitPublisher;
    private final AppProperties props;
    private final Executor evalExecutor;

    public AdminController(SessionRepository sessionRepository, MessageRepository messageRepository,
                           TraceRepository traceRepository, SpanRepository spanRepository,
                           LlmCallRepository llmCallRepository, ApprovalRepository approvalRepository,
                           EvalRepository evalRepository, StatsRepository statsRepository,
                           ModelRouter modelRouter, EvalRunner evalRunner, RabbitPublisher rabbitPublisher,
                           AppProperties props, @Qualifier("evalExecutor") Executor evalExecutor) {
        this.sessionRepository = sessionRepository;
        this.messageRepository = messageRepository;
        this.traceRepository = traceRepository;
        this.spanRepository = spanRepository;
        this.llmCallRepository = llmCallRepository;
        this.approvalRepository = approvalRepository;
        this.evalRepository = evalRepository;
        this.statsRepository = statsRepository;
        this.modelRouter = modelRouter;
        this.evalRunner = evalRunner;
        this.rabbitPublisher = rabbitPublisher;
        this.props = props;
        this.evalExecutor = evalExecutor;
    }

    @GetMapping("/overview")
    public ApiResponse<AdminDtos.OverviewVO> overview(
            @RequestParam(value = "days", defaultValue = "7") int days) {
        LocalDateTime since = since(days);
        long totalSessions = sessionRepository.countSince(since);
        long totalMessages = messageRepository.countSince(since);
        long traces = traceRepository.countSince(since);
        long success = traceRepository.countSuccessSince(since);
        double successRate = traces == 0 ? 0d : round4(success / (double) traces);

        List<Integer> latencies = traceRepository.latenciesSince(since, 2000);
        long avgLatency = 0L;
        if (!latencies.isEmpty()) {
            long sum = 0L;
            for (Integer value : latencies) {
                sum += value == null ? 0 : value;
            }
            avgLatency = Math.round(sum / (double) latencies.size());
        }
        long p95 = percentile95(latencies);

        long totalCost = llmCallRepository.sumCostSince(since);
        double costPerSuccess = success == 0 ? 0d : round2(totalCost / (double) success);
        long approvalPending = approvalRepository.countPending();
        long toolCalls = spanRepository.countToolCallsSince(since);
        long toolErrors = spanRepository.countToolErrorsSince(since);
        double toolErrorRate = toolCalls == 0 ? 0d : round4(toolErrors / (double) toolCalls);

        List<AdminDtos.TopToolVO> topTools = new ArrayList<>();
        for (SpanRepository.ToolCount tool : spanRepository.topToolsSince(since, 5)) {
            topTools.add(new AdminDtos.TopToolVO(tool.name(), tool.count()));
        }

        return ApiResponse.ok(new AdminDtos.OverviewVO(totalSessions, totalMessages, successRate,
                avgLatency, p95, totalCost, costPerSuccess, approvalPending, toolErrorRate, topTools,
                trend(since)));
    }

    @GetMapping("/traces")
    public ApiResponse<List<AdminDtos.TraceVO>> traces(
            @RequestParam(value = "sessionId", required = false) Long sessionId,
            @RequestParam(value = "status", required = false) String status,
            @RequestParam(value = "limit", defaultValue = "20") int limit) {
        int normalizedLimit = Math.max(1, Math.min(limit, MAX_TRACE_LIMIT));
        List<AdminDtos.TraceVO> items = new ArrayList<>();
        for (TraceRepository.TraceRow row : traceRepository.list(sessionId, status, normalizedLimit)) {
            items.add(toTraceVO(row));
        }
        return ApiResponse.ok(items);
    }

    @GetMapping("/traces/{traceId}")
    public ApiResponse<AdminDtos.TraceDetailVO> trace(@PathVariable("traceId") String traceId) {
        TraceRepository.TraceRow row = traceRepository.findByTraceId(traceId);
        if (row == null) {
            throw BizException.notFound("链路不存在: " + traceId);
        }
        List<AdminDtos.SpanVO> spans = new ArrayList<>();
        for (SpanRepository.SpanRow span : spanRepository.listByTrace(traceId)) {
            spans.add(new AdminDtos.SpanVO(span.spanId(), span.parentSpanId(), span.name(),
                    span.spanType(), span.seq(), JsonUtil.parseMap(span.inputJson()),
                    JsonUtil.parseMap(span.outputJson()), span.latencyMs(), span.status()));
        }
        boolean replayable = !"RUNNING".equals(row.status()) && !spans.isEmpty();
        return ApiResponse.ok(new AdminDtos.TraceDetailVO(toTraceVO(row), spans, replayable));
    }

    @GetMapping("/costs")
    public ApiResponse<AdminDtos.CostsVO> costs(
            @RequestParam(value = "days", defaultValue = "7") int days) {
        LocalDateTime since = since(days);
        long total = llmCallRepository.sumCostSince(since);

        List<AdminDtos.ModelCostVO> byModel = new ArrayList<>();
        for (LlmCallRepository.ModelAgg row : llmCallRepository.byModel(since, 10)) {
            byModel.add(new AdminDtos.ModelCostVO(row.model(), row.calls(), row.costCents()));
        }
        List<AdminDtos.ProviderCostVO> byProvider = new ArrayList<>();
        for (LlmCallRepository.ProviderAgg row : llmCallRepository.byProvider(since)) {
            byProvider.add(new AdminDtos.ProviderCostVO(row.provider(), row.costCents()));
        }
        List<AdminDtos.DailyCostVO> daily = new ArrayList<>();
        for (LlmCallRepository.DailyAgg row : llmCallRepository.daily(since)) {
            daily.add(new AdminDtos.DailyCostVO(row.date(), row.calls(), row.costCents()));
        }
        return ApiResponse.ok(new AdminDtos.CostsVO(total, byModel, byProvider, daily));
    }

    @GetMapping("/models")
    public ApiResponse<List<AdminDtos.ModelStatusVO>> models() {
        List<AdminDtos.ModelStatusVO> items = new ArrayList<>();
        for (ModelRouter.ModelStatus status : modelRouter.statuses()) {
            items.add(new AdminDtos.ModelStatusVO(status.provider(), status.model(), status.role(),
                    status.healthy(), status.circuit(), status.avgLatencyMs(), status.calls()));
        }
        return ApiResponse.ok(items);
    }

    /**
     * 启动评测：先落 eval_run（RUNNING）并立即返回 runId；
     * MQ 开启时由 eval.batch 消费者执行，关闭时退化为进程内 evalExecutor 执行。
     */
    @PostMapping("/evals/run")
    public ApiResponse<AdminDtos.EvalRunStartVO> runEval(
            @RequestBody(required = false) AdminDtos.EvalRunReq req) {
        String suite = req == null || req.suite() == null || req.suite().isBlank()
                ? "shopping" : req.suite().trim();
        int repeat = req == null || req.repeat() == null
                ? Math.max(1, props.getEval().getDefaultRepeat())
                : Math.max(1, Math.min(req.repeat(), MAX_EVAL_REPEAT));
        long runId = evalRepository.insertRun(suite, repeat);
        if (props.getMq().isEnabled()) {
            rabbitPublisher.publishEvalBatch(runId, suite);
        } else {
            evalExecutor.execute(() -> {
                evalRunner.run(runId);
            });
        }
        return ApiResponse.ok(new AdminDtos.EvalRunStartVO(runId, "RUNNING"));
    }

    @GetMapping("/evals/runs")
    public ApiResponse<List<AdminDtos.EvalRunVO>> evalRuns(
            @RequestParam(value = "limit", defaultValue = "20") int limit) {
        int normalizedLimit = Math.max(1, Math.min(limit, 100));
        List<AdminDtos.EvalRunVO> items = new ArrayList<>();
        for (EvalRepository.EvalRunRow row : evalRepository.listRuns(normalizedLimit)) {
            items.add(toEvalRunVO(row, false));
        }
        return ApiResponse.ok(items);
    }

    @GetMapping("/evals/runs/{id}")
    public ApiResponse<AdminDtos.EvalRunVO> evalRun(@PathVariable("id") long id) {
        EvalRepository.EvalRunRow row = evalRepository.findRun(id);
        if (row == null) {
            throw BizException.notFound("评测批次不存在: " + id);
        }
        return ApiResponse.ok(toEvalRunVO(row, true));
    }

    private AdminDtos.TraceVO toTraceVO(TraceRepository.TraceRow row) {
        return new AdminDtos.TraceVO(row.traceId(), row.sessionId(), row.agentType(), row.status(),
                row.totalLatencyMs(), row.totalCostCents(), row.stepCount());
    }

    private AdminDtos.EvalRunVO toEvalRunVO(EvalRepository.EvalRunRow row, boolean withCases) {
        List<AdminDtos.EvalCaseVO> cases = new ArrayList<>();
        if (withCases) {
            for (EvalRepository.EvalCaseRow item : evalRepository.cases(row.id())) {
                cases.add(new AdminDtos.EvalCaseVO(item.caseId(), item.question(), item.expected(),
                        item.actual(), item.passed(), decimal(item.score())));
            }
        }
        return new AdminDtos.EvalRunVO(row.id(), row.suite(), row.status(), row.total(), row.passed(),
                decimal(row.passRate()), decimal(row.passK()), row.avgCostCents(), row.avgLatencyMs(),
                cases);
    }

    /** overview.trend：按天合并会话数与成本（TreeMap 保证日期升序）。 */
    private List<AdminDtos.TrendPointVO> trend(LocalDateTime since) {
        Map<String, long[]> byDate = new TreeMap<>();
        for (StatsRepository.DailyCount row : statsRepository.dailySessions(since)) {
            byDate.computeIfAbsent(row.date(), key -> new long[2])[0] = row.count();
        }
        for (LlmCallRepository.DailyAgg row : llmCallRepository.daily(since)) {
            byDate.computeIfAbsent(row.date(), key -> new long[2])[1] = row.costCents();
        }
        List<AdminDtos.TrendPointVO> points = new ArrayList<>(byDate.size());
        for (Map.Entry<String, long[]> entry : byDate.entrySet()) {
            points.add(new AdminDtos.TrendPointVO(entry.getKey(), entry.getValue()[0],
                    entry.getValue()[1]));
        }
        points.sort(Comparator.comparing(AdminDtos.TrendPointVO::date));
        return points;
    }

    private long percentile95(List<Integer> latencies) {
        if (latencies == null || latencies.isEmpty()) {
            return 0L;
        }
        List<Integer> sorted = new ArrayList<>(latencies);
        sorted.sort(Comparator.naturalOrder());
        int index = (int) Math.ceil(sorted.size() * 0.95d) - 1;
        if (index < 0) {
            index = 0;
        }
        if (index >= sorted.size()) {
            index = sorted.size() - 1;
        }
        Integer value = sorted.get(index);
        return value == null ? 0L : value;
    }

    private LocalDateTime since(int days) {
        int window = Math.max(1, Math.min(days, 90));
        return LocalDate.now().minusDays(window - 1L).atStartOfDay();
    }

    private double decimal(BigDecimal value) {
        return value == null ? 0d : value.doubleValue();
    }

    private double round4(double value) {
        return Math.round(value * 10000d) / 10000d;
    }

    private double round2(double value) {
        return Math.round(value * 100d) / 100d;
    }
}
