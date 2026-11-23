package com.xingtu.agent.eval;

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.infra.repo.EvalRepository;
import com.xingtu.agent.llm.CostCalculator;
import com.xingtu.agent.llm.FallbackChain;
import com.xingtu.agent.llm.LlmProvider;
import com.xingtu.agent.llm.ModelRouter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 评测执行器：按 eval_run.repeat_times 对每个用例重复采样，落 eval_case_result 并汇总 eval_run。
 *
 * <p>指标口径：
 * <ul>
 *   <li>passRate = 至少一次通过的用例数 / 用例总数（pass@k）</li>
 *   <li>passK = k 次全部通过的用例数 / 用例总数（pass^k）</li>
 * </ul>
 * repeat=1 时两者相等。单用例调用失败不中断整批，记为 failed 并继续。</p>
 */
@Component
public class EvalRunner {

    private static final Logger log = LoggerFactory.getLogger(EvalRunner.class);
    private static final int MAX_COMPLETION_TOKENS = 400;

    private final EvalRepository evalRepository;
    private final EvalDataset dataset;
    private final EvalJudge judge;
    private final ModelRouter modelRouter;
    private final CostCalculator costCalculator;
    private final FallbackChain fallbackChain;

    public EvalRunner(EvalRepository evalRepository, EvalDataset dataset, EvalJudge judge,
                      ModelRouter modelRouter, CostCalculator costCalculator,
                      FallbackChain fallbackChain) {
        this.evalRepository = evalRepository;
        this.dataset = dataset;
        this.judge = judge;
        this.modelRouter = modelRouter;
        this.costCalculator = costCalculator;
        this.fallbackChain = fallbackChain;
    }

    /** 执行一个已落库的评测批次；返回最终批次行（异常时状态为 FAILED）。 */
    public EvalRepository.EvalRunRow run(long runId) {
        EvalRepository.EvalRunRow run = evalRepository.findRun(runId);
        if (run == null) {
            log.warn("评测批次不存在，跳过执行 runId={}", runId);
            return null;
        }
        List<EvalDataset.EvalCase> cases = dataset.cases(run.suite());
        int repeat = Math.max(1, run.repeatTimes());
        int passed = 0;
        int allPassed = 0;
        int attempts = 0;
        long costSum = 0L;
        long latencySum = 0L;
        List<Map<String, Object>> caseReports = new ArrayList<>();
        try {
            for (EvalDataset.EvalCase testCase : cases) {
                boolean anyPassed = false;
                boolean allAttemptsPassed = true;
                String lastActual = "";
                double lastScore = 0d;
                List<Map<String, Object>> attemptReports = new ArrayList<>();
                for (int attempt = 1; attempt <= repeat; attempt++) {
                    long startedAt = System.currentTimeMillis();
                    String actual;
                    int costCents = 0;
                    EvalJudge.Judgment judgment;
                    try {
                        LlmProvider.Result result = modelRouter.chat(buildRequest(testCase));
                        actual = result.text() == null ? "" : result.text();
                        costCents = costCalculator.costCents(result.model(), result.promptTokens(),
                                result.completionTokens());
                        judgment = judge.judge(testCase, actual);
                    } catch (RuntimeException e) {
                        actual = "ERROR: " + (e.getMessage() == null ? e.toString() : e.getMessage());
                        judgment = new EvalJudge.Judgment(false, 0d, "调用失败");
                        log.warn("评测用例调用失败 caseId={} : {}", testCase.caseId(), e.getMessage());
                    }
                    long latencyMs = System.currentTimeMillis() - startedAt;
                    attempts++;
                    costSum += costCents;
                    latencySum += latencyMs;
                    anyPassed = anyPassed || judgment.passed();
                    allAttemptsPassed = allAttemptsPassed && judgment.passed();
                    lastActual = actual;
                    lastScore = judgment.score();

                    Map<String, Object> attemptReport = new LinkedHashMap<>();
                    attemptReport.put("attempt", attempt);
                    attemptReport.put("passed", judgment.passed());
                    attemptReport.put("score", judgment.score());
                    attemptReport.put("reason", judgment.reason());
                    attemptReport.put("latencyMs", latencyMs);
                    attemptReport.put("costCents", costCents);
                    attemptReports.add(attemptReport);
                }
                if (anyPassed) {
                    passed++;
                }
                if (allAttemptsPassed && repeat > 0) {
                    allPassed++;
                }
                Map<String, Object> detail = new LinkedHashMap<>();
                detail.put("attempts", attemptReports);
                evalRepository.insertCase(runId, testCase.caseId(), testCase.question(),
                        testCase.expected(), lastActual, anyPassed, lastScore, repeat,
                        JsonUtil.toJson(detail));

                Map<String, Object> caseReport = new LinkedHashMap<>();
                caseReport.put("caseId", testCase.caseId());
                caseReport.put("passed", anyPassed);
                caseReport.put("score", lastScore);
                caseReport.put("attempts", attemptReports);
                caseReports.add(caseReport);
            }

            double passRate = cases.isEmpty() ? 0d : round4(passed / (double) cases.size());
            double passK = cases.isEmpty() ? 0d : round4(allPassed / (double) cases.size());
            int avgCostCents = attempts == 0 ? 0 : (int) Math.round(costSum / (double) attempts);
            int avgLatencyMs = attempts == 0 ? 0 : (int) Math.round(latencySum / (double) attempts);

            Map<String, Object> report = new LinkedHashMap<>();
            report.put("suite", run.suite());
            report.put("repeat", repeat);
            report.put("passRate", passRate);
            report.put("passK", passK);
            report.put("cases", caseReports);
            evalRepository.finishRun(runId, "SUCCESS", cases.size(), passed, passRate, passK,
                    avgCostCents, avgLatencyMs, JsonUtil.toJson(report));
        } catch (RuntimeException e) {
            log.error("评测执行失败 runId={}", runId, e);
            Map<String, Object> report = new LinkedHashMap<>();
            report.put("suite", run.suite());
            report.put("error", e.getMessage() == null ? e.toString() : e.getMessage());
            report.put("finishedCases", caseReports.size());
            evalRepository.finishRun(runId, "FAILED", cases.size(), passed, 0d, 0d, 0, 0,
                    JsonUtil.toJson(report));
        }
        return evalRepository.findRun(runId);
    }

    /**
     * 评测 prompt。mock 模式额外注入 STEP / TOOL_RESULT，让规则型 Mock 模型直接产出
     * 「第二轮最终答案」而不是工具调用 JSON，保证离线评测可复现。
     */
    private LlmProvider.Request buildRequest(EvalDataset.EvalCase testCase) {
        List<LlmProvider.Message> messages = new ArrayList<>();
        messages.add(LlmProvider.Message.system(
                "你是星图商城的智能客服/导购助手。回答必须基于商城事实，不得编造订单、价格或政策；"
                        + "涉及退款、删单等不可逆动作时说明需要人工审批。"));
        StringBuilder user = new StringBuilder();
        user.append("QUESTION: ").append(testCase.question()).append('\n');
        if (fallbackChain.mockMode()) {
            user.append("STEP: 3\n");
            user.append("TOOL_RESULT ok=true summary=已获取商品、订单与知识库检索结果\n");
        }
        user.append("请用中文直接回答用户，不要输出 JSON，不要调用工具。");
        messages.add(LlmProvider.Message.user(user.toString()));
        return new LlmProvider.Request(messages, 0d, MAX_COMPLETION_TOKENS);
    }

    private double round4(double value) {
        return Math.round(value * 10000d) / 10000d;
    }
}
