package com.xingtu.agent.mq;

// ═══════ 文件级能力标注 ═══════
// [CAP-14] 可靠性/降级
// 职责：退款异步消费者：refund
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.RabbitConfig;
import com.xingtu.agent.infra.repo.AsyncTaskRepository;
import com.xingtu.agent.infra.repo.RefundRepository;
import com.xingtu.agent.service.RefundService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 退款异步消费者：refund.execute（契约第 8 节）。
 *
 * <p>审批通过后把已落库的退款申请推进到 SUCCESS；以 refund_request 当前状态做幂等，
 * 重复投递不会产生二次退款。</p>
 */
@Component
@ConditionalOnProperty(prefix = "app.mq", name = "enabled", havingValue = "true", matchIfMissing = true)
public class RefundConsumer {

    private static final Logger log = LoggerFactory.getLogger(RefundConsumer.class);

    private final RefundService refundService;
    private final RefundRepository refundRepository;
    private final AsyncTaskRepository asyncTaskRepository;

    public RefundConsumer(RefundService refundService, RefundRepository refundRepository,
                          AsyncTaskRepository asyncTaskRepository) {
        this.refundService = refundService;
        this.refundRepository = refundRepository;
        this.asyncTaskRepository = asyncTaskRepository;
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_REFUND_EXECUTE)
    public void onRefund(Object payload) {
        Map<String, Object> data = MqSupport.toMap(payload);
        long refundId = MqSupport.longValue(data, "refundId");
        long approvalId = MqSupport.longValue(data, "approvalId");
        MqSupport.retry("REFUND_EXECUTE", data, asyncTaskRepository, log,
                () -> execute(refundId, approvalId));
    }

    private void execute(long refundId, long approvalId) {
        if (refundId <= 0) {
            throw new IllegalArgumentException("refundId 缺失");
        }
        RefundRepository.RefundRow row = refundService.findById(refundId);
        if (row == null) {
            throw new IllegalStateException("退款单不存在 refundId=" + refundId);
        }
        if ("SUCCESS".equals(row.status())) {
            log.info("退款单已是 SUCCESS，跳过重复执行 refundId={} approvalId={}", refundId, approvalId);
            return;
        }
        if (!refundService.markSuccess(refundId)) {
            throw new IllegalStateException("退款单状态更新失败 refundId=" + refundId);
        }
        log.info("退款执行完成 refundId={} refundNo={} approvalId={}", refundId, row.refundNo(),
                approvalId);
    }
}
