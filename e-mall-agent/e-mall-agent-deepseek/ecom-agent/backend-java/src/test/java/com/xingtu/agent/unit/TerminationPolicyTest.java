package com.xingtu.agent.unit;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：TerminationPolicyTest
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.agent.AgentState;
import com.xingtu.agent.agent.TerminationPolicy;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class TerminationPolicyTest {

    private AgentState state(long startedAt, long timeoutMillis) {
        return new AgentState("trace-1", 1L, 2L, "帮我找手机", startedAt, timeoutMillis);
    }

    @Test
    void continuesWhenNothingTerminates() {
        TerminationPolicy policy = new TerminationPolicy(10, 100_000, 60_000);
        AgentState state = state(System.currentTimeMillis(), 60_000);
        assertFalse(policy.check(state, System.currentTimeMillis()).stop());
    }

    @Test
    void stopsOnFinalAnswer() {
        TerminationPolicy policy = new TerminationPolicy(10, 100_000, 60_000);
        AgentState state = state(System.currentTimeMillis(), 60_000);
        state.setFinalAnswer("推荐这三款手机");
        TerminationPolicy.Verdict verdict = policy.check(state, System.currentTimeMillis());
        assertTrue(verdict.stop());
        assertEquals(TerminationPolicy.Reason.FINAL_ANSWER, verdict.reason());
        assertEquals("stop", policy.finishReason(verdict.reason()));
    }

    @Test
    void stopsAtMaxSteps() {
        TerminationPolicy policy = new TerminationPolicy(3, 100_000, 60_000);
        AgentState state = state(System.currentTimeMillis(), 60_000);
        state.beginStep();
        state.beginStep();
        state.beginStep();
        TerminationPolicy.Verdict verdict = policy.check(state, System.currentTimeMillis());
        assertEquals(TerminationPolicy.Reason.MAX_STEPS, verdict.reason());
        assertEquals("max_steps", policy.finishReason(verdict.reason()));
    }

    @Test
    void stopsWhenTokenBudgetExhausted() {
        TerminationPolicy policy = new TerminationPolicy(10, 100, 60_000);
        AgentState state = state(System.currentTimeMillis(), 60_000);
        state.addUsage(60, 50, 1);
        assertEquals(TerminationPolicy.Reason.TOKEN_BUDGET,
                policy.check(state, System.currentTimeMillis()).reason());
    }

    @Test
    void stopsWhenTaskTimesOut() {
        long startedAt = System.currentTimeMillis() - 5_000L;
        TerminationPolicy policy = new TerminationPolicy(10, 100_000, 1_000);
        AgentState state = state(startedAt, 1_000);
        TerminationPolicy.Verdict verdict = policy.check(state, System.currentTimeMillis());
        assertEquals(TerminationPolicy.Reason.TIMEOUT, verdict.reason());
        assertEquals("interrupted", policy.finishReason(verdict.reason()));
    }

    @Test
    void stopsOnNoProgress() {
        TerminationPolicy policy = new TerminationPolicy(10, 100_000, 60_000);
        AgentState state = state(System.currentTimeMillis(), 60_000);
        state.noteInfo("相同的信息");
        state.noteInfo("相同的信息");
        state.noteInfo("相同的信息");
        assertEquals(2, state.getConsecutiveNoProgress());
        assertEquals(TerminationPolicy.Reason.NO_PROGRESS,
                policy.check(state, System.currentTimeMillis()).reason());
    }

    @Test
    void stopsOnRepeatedToolCallLoop() {
        TerminationPolicy policy = new TerminationPolicy(10, 100_000, 60_000);
        AgentState state = state(System.currentTimeMillis(), 60_000);
        state.recordToolCall("c1", "search_products", Map.of("query", "手机"), "READ");
        state.recordToolCall("c2", "search_products", Map.of("query", "手机"), "READ");
        assertEquals(2, state.getLastSignatureCount());
        assertEquals(TerminationPolicy.Reason.LOOP_DETECTED,
                policy.check(state, System.currentTimeMillis()).reason());
    }

    @Test
    void stopsWhenApprovalRequired() {
        TerminationPolicy policy = new TerminationPolicy(10, 100_000, 60_000);
        AgentState state = state(System.currentTimeMillis(), 60_000);
        state.setPendingApprovalId(7L);
        TerminationPolicy.Verdict verdict = policy.check(state, System.currentTimeMillis());
        assertEquals(TerminationPolicy.Reason.APPROVAL_REQUIRED, verdict.reason());
        assertEquals("approval_required", policy.finishReason(verdict.reason()));
    }

    @Test
    void finishReasonHandlesNullAndUnknown() {
        TerminationPolicy policy = new TerminationPolicy(10, 100_000, 60_000);
        assertEquals("max_steps", policy.finishReason(null));
        assertEquals("stop", policy.finishReason(TerminationPolicy.Reason.NONE));
    }
}
