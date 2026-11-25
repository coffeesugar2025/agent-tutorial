package com.xingtu.agent.service;

// ═══════ 文件级能力标注 ═══════
// [CAP-08] 工作流/状态机  |  [CAP-10] 人机协作 HITL
// 职责：退款服务：资格校验 + 幂等创建 + 审批后执行
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.Ids;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.infra.RabbitPublisher;
import com.xingtu.agent.infra.repo.AuditRepository;
import com.xingtu.agent.infra.repo.IdempotencyRepository;
import com.xingtu.agent.infra.repo.OrderRepository;
import com.xingtu.agent.infra.repo.RefundRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 退款服务：资格校验 + 幂等创建 + 审批后执行。
 *
 * <p>幂等三重保障：refund_request.idempotency_key 唯一索引（先查后插 + 捕获重复键）、
 * idempotency_record 结果缓存、refund_no 唯一。</p>
 */
@Service
public class RefundService {

    private static final Logger log = LoggerFactory.getLogger(RefundService.class);
    private static final int RETURN_WINDOW_DAYS = 7;

    public record Eligibility(boolean eligible, String reason, String orderNo, String orderStatus,
                              BigDecimal maxAmount) {
    }

    public record Outcome(long refundId, String refundNo, String status, boolean replayed) {
    }

    private final OrderRepository orderRepository;
    private final RefundRepository refundRepository;
    private final IdempotencyRepository idempotencyRepository;
    private final RabbitPublisher publisher;
    private final AuditRepository auditRepository;

    public RefundService(OrderRepository orderRepository, RefundRepository refundRepository,
                         IdempotencyRepository idempotencyRepository, RabbitPublisher publisher,
                         AuditRepository auditRepository) {
        this.orderRepository = orderRepository;
        this.refundRepository = refundRepository;
        this.idempotencyRepository = idempotencyRepository;
        this.publisher = publisher;
        this.auditRepository = auditRepository;
    }

    /** 解析订单：orderNo 为 LATEST / 空时取用户最近一笔订单。 */
    public OrderRepository.OrderRow resolveOrder(long userId, String orderNo) {
        if (orderNo == null || orderNo.isBlank() || "LATEST".equalsIgnoreCase(orderNo)) {
            return orderRepository.findLatestByUser(userId);
        }
        return orderRepository.findByOrderNo(orderNo.trim());
    }

    public Eligibility checkEligibility(long userId, String orderNo) {
        OrderRepository.OrderRow order = resolveOrder(userId, orderNo);
        if (order == null) {
            return new Eligibility(false, "未找到可退款的订单", orderNo, null, BigDecimal.ZERO);
        }
        if (order.userId() != userId) {
            return new Eligibility(false, "订单不属于当前用户", order.orderNo(), order.status(),
                    BigDecimal.ZERO);
        }
        if ("CANCELLED".equals(order.status()) || "REFUNDED".equals(order.status())
                || "REFUNDING".equals(order.status())) {
            return new Eligibility(false, "订单状态 " + order.status() + " 不支持退款", order.orderNo(),
                    order.status(), BigDecimal.ZERO);
        }
        LocalDateTime reference = order.finishedAt() != null ? order.finishedAt()
                : order.paidAt() != null ? order.paidAt() : order.createdAt();
        if (reference != null && reference.plusDays(RETURN_WINDOW_DAYS).isBefore(LocalDateTime.now())) {
            return new Eligibility(false, "已超过 " + RETURN_WINDOW_DAYS + " 天无理由退货期",
                    order.orderNo(), order.status(), order.payAmount());
        }
        BigDecimal max = order.payAmount() == null ? order.totalAmount() : order.payAmount();
        return new Eligibility(true, "符合退款条件", order.orderNo(), order.status(),
                max == null ? BigDecimal.ZERO : max);
    }

    /**
     * 幂等创建退款申请。同一 idempotencyKey 重复调用返回首次结果。
     */
    public Outcome create(long userId, String orderNo, String reason, BigDecimal amount,
                          String idempotencyKey, Long approvalId) {
        String key = idempotencyKey == null || idempotencyKey.isBlank()
                ? "refund:" + userId + ":" + (orderNo == null ? "LATEST" : orderNo)
                : idempotencyKey.trim();

        RefundRepository.RefundRow existing = refundRepository.findByIdempotencyKey(key);
        if (existing != null) {
            return new Outcome(existing.id(), existing.refundNo(), existing.status(), true);
        }
        IdempotencyRepository.IdemRow cached = idempotencyRepository.find(key);
        if (cached != null && cached.resultJson() != null) {
            Map<String, Object> result = JsonUtil.parseMap(cached.resultJson());
            return new Outcome(longValue(result.get("refundId")), String.valueOf(result.get("refundNo")),
                    String.valueOf(result.get("status")), true);
        }

        OrderRepository.OrderRow order = resolveOrder(userId, orderNo);
        if (order == null) {
            throw BizException.notFound("未找到可退款的订单");
        }
        if (order.userId() != userId) {
            throw BizException.forbidden("订单不属于当前用户");
        }
        Eligibility eligibility = checkEligibility(userId, order.orderNo());
        if (!eligibility.eligible() && approvalId == null) {
            throw BizException.validation(eligibility.reason());
        }
        BigDecimal finalAmount = amount == null || amount.compareTo(BigDecimal.ZERO) <= 0
                ? eligibility.maxAmount() : amount.min(eligibility.maxAmount());
        if (finalAmount.compareTo(BigDecimal.ZERO) <= 0) {
            throw BizException.validation("退款金额必须大于 0");
        }

        String refundNo = Ids.refundNo();
        String status = approvalId == null ? "PENDING_APPROVAL" : "APPROVED";
        long refundId;
        try {
            refundId = refundRepository.insert(refundNo, order.id(), userId,
                    reason == null || reason.isBlank() ? "用户申请退款" : reason.trim(),
                    finalAmount, status, key, approvalId);
        } catch (DuplicateKeyException e) {
            RefundRepository.RefundRow duplicated = refundRepository.findByIdempotencyKey(key);
            if (duplicated == null) {
                throw BizException.conflict("并发创建退款失败，请重试");
            }
            log.info("幂等命中退款申请 refundNo={}", duplicated.refundNo());
            return new Outcome(duplicated.id(), duplicated.refundNo(), duplicated.status(), true);
        }

        Map<String, Object> record = new LinkedHashMap<>();
        record.put("refundId", refundId);
        record.put("refundNo", refundNo);
        record.put("status", status);
        idempotencyRepository.save(key, "refund", JsonUtil.toJson(record),
                LocalDateTime.now().plusDays(7));

        Map<String, Object> audit = new LinkedHashMap<>();
        audit.put("refundNo", refundNo);
        audit.put("orderNo", order.orderNo());
        audit.put("amount", finalAmount);
        audit.put("approvalId", approvalId);
        auditRepository.insert(userId, "CREATE_REFUND", refundNo, JsonUtil.toJson(audit), null);

        if (approvalId != null) {
            publisher.publishRefundExecute(refundId, approvalId);
        }
        return new Outcome(refundId, refundNo, status, false);
    }

    /** 审批通过后执行退款（由 ApprovalService 调用）。 */
    public Outcome executeApprovedRefund(long userId, Map<String, Object> detail, long approvalId) {
        String orderNo = stringValue(detail.get("orderNo"));
        String reason = stringValue(detail.get("reason"));
        String idempotencyKey = stringValue(detail.get("idempotencyKey"));
        BigDecimal amount = decimalValue(detail.get("amount"));
        Outcome outcome = create(userId, orderNo, reason, amount, idempotencyKey, approvalId);
        if (!outcome.replayed()) {
            refundRepository.updateStatus(outcome.refundId(), "APPROVED");
            orderRepository.updateStatus(orderIdOf(orderNo, userId), null, "REFUNDING");
        }
        return outcome;
    }

    /** MQ 消费者：把已审批退款推进到 SUCCESS。 */
    public boolean markSuccess(long refundId) {
        return refundRepository.updateStatus(refundId, "SUCCESS");
    }

    public RefundRepository.RefundRow findById(long refundId) {
        return refundRepository.findById(refundId);
    }

    private long orderIdOf(String orderNo, long userId) {
        OrderRepository.OrderRow order = resolveOrder(userId, orderNo);
        return order == null ? 0L : order.id();
    }

    private String stringValue(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private long longValue(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text) {
            try {
                return Long.parseLong(text);
            } catch (NumberFormatException e) {
                return 0L;
            }
        }
        return 0L;
    }

    private BigDecimal decimalValue(Object value) {
        if (value instanceof BigDecimal decimal) {
            return decimal;
        }
        if (value instanceof Number number) {
            return BigDecimal.valueOf(number.doubleValue());
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return new BigDecimal(text);
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }
}
