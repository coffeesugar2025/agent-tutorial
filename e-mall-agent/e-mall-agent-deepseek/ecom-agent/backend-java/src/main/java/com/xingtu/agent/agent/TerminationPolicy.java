package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：终止策略：实现 docs/00 第 5 节的 7 条终止条件，每条都有独立可测的判定
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;

/**
 * 终止策略：实现 docs/00 第 5 节的 7 条终止条件，每条都有独立可测的判定。
 *
 * <ol>
 *   <li>模型输出最终答案（无 tool_call）</li>
 *   <li>step &gt;= MAX_STEPS</li>
 *   <li>tokens &gt;= MAX_TOKEN_BUDGET</li>
 *   <li>耗时 &gt;= TASK_TIMEOUT_SECONDS</li>
 *   <li>连续 2 步无新增信息</li>
 *   <li>同一工具 + 同一参数连续调用 2 次</li>
 *   <li>触发 IRREVERSIBLE 工具，挂起等审批</li>
 * </ol>
 */
public class TerminationPolicy {

    public enum Reason {
        NONE,
        FINAL_ANSWER,
        MAX_STEPS,
        TOKEN_BUDGET,
        TIMEOUT,
        NO_PROGRESS,
        LOOP_DETECTED,
        APPROVAL_REQUIRED
    }

    public record Verdict(boolean stop, Reason reason) {
        public static Verdict go() {
            return new Verdict(false, Reason.NONE);
        }

        public static Verdict stop(Reason reason) {
            return new Verdict(true, reason);
        }
    }

    private final int maxSteps;
    private final int maxTokenBudget;
    private final long timeoutMillis;

    public TerminationPolicy(int maxSteps, int maxTokenBudget, long timeoutMillis) {
        this.maxSteps = Math.max(1, maxSteps);
        this.maxTokenBudget = Math.max(1, maxTokenBudget);
        this.timeoutMillis = Math.max(1L, timeoutMillis);
    }

    public static TerminationPolicy from(AppProperties props) {
        return new TerminationPolicy(props.getAgent().getMaxSteps(),
                props.getAgent().getMaxTokenBudget(),
                props.getAgent().getTaskTimeoutSeconds() * 1000L);
    }

    // ──────── [CAP-03] 运行时循环 ────────
    //   本处：7 条终止条件
    //   域约束：判定顺序固定为 超时→步数→预算→循环→无进展，同时命中也必须稳定返回同一个原因
    public Verdict check(AgentState state, long nowMillis) {
        if (state == null) {
            return Verdict.stop(Reason.FINAL_ANSWER);
        }
        if (state.hasFinalAnswer()) {
            return Verdict.stop(Reason.FINAL_ANSWER);
        }
        if (state.getStep() >= maxSteps) {
            return Verdict.stop(Reason.MAX_STEPS);
        }
        if (state.totalTokens() >= maxTokenBudget) {
            return Verdict.stop(Reason.TOKEN_BUDGET);
        }
        if (nowMillis - state.getStartedAt() >= timeoutMillis) {
            return Verdict.stop(Reason.TIMEOUT);
        }
        if (state.getConsecutiveNoProgress() >= 2) {
            return Verdict.stop(Reason.NO_PROGRESS);
        }
        if (state.getLastSignatureCount() >= 2) {
            return Verdict.stop(Reason.LOOP_DETECTED);
        }
        if (state.getPendingApprovalId() != null) {
            return Verdict.stop(Reason.APPROVAL_REQUIRED);
        }
        return Verdict.go();
    }

    /** 终止原因 -> 契约 finishReason（stop / interrupted / approval_required / max_steps / error）。 */
    public String finishReason(Reason reason) {
        if (reason == null) {
            return "max_steps";
        }
        switch (reason) {
            case FINAL_ANSWER:
                return "stop";
            case TIMEOUT:
                return "interrupted";
            case APPROVAL_REQUIRED:
                return "approval_required";
            case MAX_STEPS:
            case TOKEN_BUDGET:
            case NO_PROGRESS:
            case LOOP_DETECTED:
                return "max_steps";
            case NONE:
            default:
                return "stop";
        }
    }

    public int maxSteps() {
        return maxSteps;
    }

    public int maxTokenBudget() {
        return maxTokenBudget;
    }

    public long timeoutMillis() {
        return timeoutMillis;
    }
}
