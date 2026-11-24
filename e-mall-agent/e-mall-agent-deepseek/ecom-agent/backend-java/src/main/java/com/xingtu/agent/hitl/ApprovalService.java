package com.xingtu.agent.hitl;

// ═══════ 文件级能力标注 ═══════
// [CAP-10] 人机协作 HITL
// 职责：人工审批：IRREVERSIBLE 工具必须先创建 approval_task 并中断， 审批通过后执行对应动作（退款 
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.infra.repo.ApprovalRepository;
import com.xingtu.agent.obs.MetricsCollector;
import com.xingtu.agent.obs.StructuredLogger;
import com.xingtu.agent.service.RefundService;

import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 人工审批：IRREVERSIBLE 工具必须先创建 approval_task 并中断，
 * 审批通过后执行对应动作（退款 / 转人工），审批拒绝或过期则不执行。
 */
@Component
public class ApprovalService {

    public static final String ACTION_CREATE_REFUND = "CREATE_REFUND";
    public static final String ACTION_ESCALATE = "ESCALATE_TO_HUMAN";
    private static final int EXPIRE_MINUTES = 30;

    public record DecisionResult(long id, String status, Map<String, Object> result) {
    }

    private final ApprovalRepository approvalRepository;
    private final RefundService refundService;
    private final MetricsCollector metrics;
    private final StructuredLogger structuredLogger;

    public ApprovalService(ApprovalRepository approvalRepository, RefundService refundService,
                           MetricsCollector metrics, StructuredLogger structuredLogger) {
        this.approvalRepository = approvalRepository;
        this.refundService = refundService;
        this.metrics = metrics;
        this.structuredLogger = structuredLogger;
    }

    /** 创建待审批任务并返回审批 ID。 */
    public ApprovalRepository.ApprovalRow create(long sessionId, Long messageId, long userId,
                                                 String actionType, String title,
                                                 Map<String, Object> detail, String risk) {
        LocalDateTime expiresAt = LocalDateTime.now().plusMinutes(EXPIRE_MINUTES);
        long id = approvalRepository.insert(sessionId, messageId, userId, actionType, title,
                JsonUtil.toJson(detail), risk, "PENDING", expiresAt);
        metrics.approvalCreated();
        structuredLogger.event("approval.created", Map.of(
                "approvalId", id, "actionType", actionType, "risk", risk));
        return approvalRepository.findById(id);
    }

    public ApprovalRequiredException require(long sessionId, Long messageId, long userId, String actionType,
                                             String title, Map<String, Object> detail, String risk) {
        ApprovalRepository.ApprovalRow row = create(sessionId, messageId, userId, actionType, title, detail,
                risk);
        return new ApprovalRequiredException(row.id(), actionType, title, detail, risk,
                JsonUtil.formatTime(row.expiresAt()));
    }

    public List<ApprovalRepository.ApprovalRow> list(long userId, String status, int limit) {
        approvalRepository.expireStale(LocalDateTime.now());
        return approvalRepository.listByUser(userId, status, limit);
    }

    public List<ApprovalRepository.ApprovalRow> listBySession(long sessionId, String status, int limit) {
        return approvalRepository.listBySession(sessionId, status, limit);
    }

    public long countPending() {
        return approvalRepository.countPending();
    }

    // ──────── [CAP-10] 人机协作 HITL ────────
    //   本处：审批决策（申请人/坐席双通道）
    //   域约束：工具本体无副作用，审批通过后才执行 approved_func；越权一律按不存在处理
    /**
     * 审批决策：APPROVE 时同步执行动作（退款走幂等插入），REJECT 仅记录。
     */
    public DecisionResult decide(long userId, long approvalId, String decision, String comment) {
        return decide(userId, approvalId, decision, comment, Collections.emptySet());
    }

    /**
     * 带角色上下文的审批决策。
     *
     * <p>权限规则与 Python 端一致：申请人本人，或具备 ADMIN / OPS 角色的坐席，均可决策。
     * 无权访问时按"不存在"处理（404），避免通过 approvalId 枚举他人审批单。</p>
     */
    public DecisionResult decide(long userId, long approvalId, String decision, String comment,
                                 Set<String> roles) {
        ApprovalRepository.ApprovalRow row = approvalRepository.findById(approvalId);
        boolean privileged = roles != null && (roles.contains("ADMIN") || roles.contains("OPS"));
        if (row == null || (row.userId() != userId && !privileged)) {
            throw BizException.notFound("审批任务不存在: " + approvalId);
        }
        if (!"PENDING".equals(row.status())) {
            throw BizException.conflict("审批任务状态为 " + row.status() + "，不可重复处理");
        }
        if (row.expiresAt() != null && row.expiresAt().isBefore(LocalDateTime.now())) {
            approvalRepository.expireStale(LocalDateTime.now());
            throw BizException.conflict("审批任务已过期，请重新发起");
        }
        String target = normalizeDecision(decision);
        Map<String, Object> result = new LinkedHashMap<>();
        if ("REJECTED".equals(target)) {
            approvalRepository.decide(approvalId, "PENDING", "REJECTED", comment, userId);
            metrics.approvalDecided();
            structuredLogger.event("approval.rejected", Map.of("approvalId", approvalId));
            result.put("message", "已拒绝，未执行任何不可逆操作");
            return new DecisionResult(approvalId, "REJECTED", result);
        }

        Map<String, Object> detail = JsonUtil.parseMap(row.detailJson());
        if (ACTION_CREATE_REFUND.equals(row.actionType())) {
            RefundService.Outcome outcome = refundService.executeApprovedRefund(userId, detail, approvalId);
            result.put("refundNo", outcome.refundNo());
            result.put("refundId", outcome.refundId());
            result.put("refundStatus", outcome.status());
        } else if (ACTION_ESCALATE.equals(row.actionType())) {
            result.put("ticketNo", "TK" + approvalId);
            result.put("message", "已转接人工客服");
        } else {
            result.put("message", "动作 " + row.actionType() + " 已记录");
        }
        approvalRepository.decide(approvalId, "PENDING", "APPROVED", comment, userId);
        metrics.approvalDecided();
        structuredLogger.event("approval.approved", Map.of("approvalId", approvalId,
                "actionType", row.actionType()));
        return new DecisionResult(approvalId, "APPROVED", result);
    }

    private String normalizeDecision(String decision) {
        if (decision == null) {
            throw BizException.validation("decision 不能为空");
        }
        String value = decision.trim().toUpperCase();
        if ("APPROVE".equals(value) || "APPROVED".equals(value)) {
            return "APPROVED";
        }
        if ("REJECT".equals(value) || "REJECTED".equals(value)) {
            return "REJECTED";
        }
        throw BizException.validation("decision 只能是 APPROVE 或 REJECT");
    }
}
