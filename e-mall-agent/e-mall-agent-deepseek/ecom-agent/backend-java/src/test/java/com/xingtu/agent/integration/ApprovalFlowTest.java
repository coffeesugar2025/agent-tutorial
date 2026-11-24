package com.xingtu.agent.integration;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：审批闭环测试：IRREVERSIBLE 动作必须「先挂起、后审批、再执行」
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.hitl.ApprovalService;
import com.xingtu.agent.infra.repo.ApprovalRepository;
import com.xingtu.agent.obs.MetricsCollector;
import com.xingtu.agent.obs.StructuredLogger;
import com.xingtu.agent.service.RefundService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/**
 * 审批闭环测试：IRREVERSIBLE 动作必须「先挂起、后审批、再执行」。
 * 全部依赖 Mockito 替身，不连数据库，不依赖 Spring 上下文。
 */
class ApprovalFlowTest {

    private ApprovalRepository approvalRepository;
    private RefundService refundService;
    private ApprovalService approvalService;

    @BeforeEach
    void setUp() {
        approvalRepository = mock(ApprovalRepository.class);
        refundService = mock(RefundService.class);
        approvalService = new ApprovalService(approvalRepository, refundService,
                mock(MetricsCollector.class), mock(StructuredLogger.class));
    }

    private ApprovalRepository.ApprovalRow pendingRefund(long approvalId, long userId) {
        return new ApprovalRepository.ApprovalRow(approvalId, 1L, 10L, userId, "CREATE_REFUND",
                "退款审批", "{\"orderNo\":\"SO202611230001\",\"amount\":3999}", "IRREVERSIBLE",
                "PENDING", null, null, LocalDateTime.now(), LocalDateTime.now().plusMinutes(30), null);
    }

    @Test
    void approveExecutesRefundAndMarksApproved() {
        when(approvalRepository.findById(7L)).thenReturn(pendingRefund(7L, 2L));
        when(refundService.executeApprovedRefund(eq(2L), anyMap(), eq(7L)))
                .thenReturn(new RefundService.Outcome(3L, "RF202611230001", "APPROVED", false));

        ApprovalService.DecisionResult result = approvalService.decide(2L, 7L, "APPROVE", "同意");

        assertEquals(7L, result.id());
        assertEquals("APPROVED", result.status());
        assertEquals("RF202611230001", result.result().get("refundNo"));
        assertEquals(3L, result.result().get("refundId"));
        verify(refundService).executeApprovedRefund(eq(2L), anyMap(), eq(7L));
        verify(approvalRepository).decide(7L, "PENDING", "APPROVED", "同意", 2L);
    }

    @Test
    void rejectNeverTouchesRefund() {
        when(approvalRepository.findById(7L)).thenReturn(pendingRefund(7L, 2L));

        ApprovalService.DecisionResult result = approvalService.decide(2L, 7L, "REJECT", "不同意");

        assertEquals("REJECTED", result.status());
        verifyNoInteractions(refundService);
        verify(approvalRepository).decide(7L, "PENDING", "REJECTED", "不同意", 2L);
    }

    @Test
    void otherUsersApprovalIsForbidden() {
        when(approvalRepository.findById(7L)).thenReturn(pendingRefund(7L, 3L));

        BizException error = assertThrows(BizException.class,
                () -> approvalService.decide(2L, 7L, "APPROVE", "越权"));

        assertEquals(40300, error.getCode());
        verify(refundService, never()).executeApprovedRefund(eq(2L), anyMap(), eq(7L));
    }

    @Test
    void alreadyDecidedIsConflict() {
        ApprovalRepository.ApprovalRow approved = new ApprovalRepository.ApprovalRow(7L, 1L, 10L, 2L,
                "CREATE_REFUND", "退款审批", "{}", "IRREVERSIBLE", "APPROVED", "同意", 2L,
                LocalDateTime.now(), LocalDateTime.now().plusMinutes(30), LocalDateTime.now());
        when(approvalRepository.findById(7L)).thenReturn(approved);

        BizException error = assertThrows(BizException.class,
                () -> approvalService.decide(2L, 7L, "APPROVE", "重复"));

        assertEquals(40900, error.getCode());
        verifyNoInteractions(refundService);
    }

    @Test
    void expiredApprovalIsConflictAndMarkedExpired() {
        ApprovalRepository.ApprovalRow expired = new ApprovalRepository.ApprovalRow(7L, 1L, 10L, 2L,
                "CREATE_REFUND", "退款审批", "{}", "IRREVERSIBLE", "PENDING", null, null,
                LocalDateTime.now().minusMinutes(40), LocalDateTime.now().minusMinutes(10), null);
        when(approvalRepository.findById(7L)).thenReturn(expired);

        BizException error = assertThrows(BizException.class,
                () -> approvalService.decide(2L, 7L, "APPROVE", "过期"));

        assertEquals(40900, error.getCode());
        verify(approvalRepository).expireStale(org.mockito.ArgumentMatchers.any(LocalDateTime.class));
        verifyNoInteractions(refundService);
    }

    @Test
    void invalidDecisionIsValidationError() {
        when(approvalRepository.findById(7L)).thenReturn(pendingRefund(7L, 2L));

        BizException error = assertThrows(BizException.class,
                () -> approvalService.decide(2L, 7L, "MAYBE", "?"));

        assertEquals(40001, error.getCode());
    }

    @Test
    void escalateApprovalCreatesTicket() {
        ApprovalRepository.ApprovalRow escalate = new ApprovalRepository.ApprovalRow(7L, 1L, 10L, 2L,
                "ESCALATE_TO_HUMAN", "转人工", "{\"reason\":\"模型全部不可用\"}", "WRITE", "PENDING",
                null, null, LocalDateTime.now(), LocalDateTime.now().plusMinutes(30), null);
        when(approvalRepository.findById(7L)).thenReturn(escalate);

        ApprovalService.DecisionResult result = approvalService.decide(2L, 7L, "APPROVE", "转人工");

        assertEquals("APPROVED", result.status());
        assertEquals("TK7", result.result().get("ticketNo"));
        verifyNoInteractions(refundService);
    }

    @Test
    void unknownApprovalIsNotFound() {
        when(approvalRepository.findById(99L)).thenReturn(null);

        BizException error = assertThrows(BizException.class,
                () -> approvalService.decide(2L, 99L, "APPROVE", "?"));

        assertEquals(40400, error.getCode());
    }

    @Test
    void approveAcceptsApprovedAlias() {
        when(approvalRepository.findById(7L)).thenReturn(pendingRefund(7L, 2L));
        when(refundService.executeApprovedRefund(eq(2L), anyMap(), eq(7L)))
                .thenReturn(new RefundService.Outcome(4L, "RF202611230002", "APPROVED", true));

        ApprovalService.DecisionResult result = approvalService.decide(2L, 7L, "approved", null);

        assertEquals("APPROVED", result.status());
        assertEquals(4L, result.result().get("refundId"));
        verify(approvalRepository).decide(7L, "PENDING", "APPROVED", null, 2L);
    }
}
