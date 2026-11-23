package com.xingtu.agent.tool;

import com.xingtu.agent.service.RefundService;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 退款工具：check_refund_eligibility（READ）、create_refund_request（IRREVERSIBLE）。
 *
 * <p>IRREVERSIBLE 工具不会在 Agent 循环里直接执行：AgentRuntime 先创建 approval_task 并中断，
 * 审批通过后由 ApprovalService 携带同样的 idempotencyKey 调用本工具的执行逻辑。</p>
 */
@Component
public class RefundTools {

    private static final List<String> AGENTS = List.of("SERVICE");

    private final RefundService refundService;

    public RefundTools(ToolRegistry registry, RefundService refundService) {
        this.refundService = refundService;
        registry.register(new ToolRegistry.Definition("check_refund_eligibility",
                "校验订单是否可退款，参数 {orderNo}；返回是否可退、原因与可退金额。",
                ToolRisk.READ, AGENTS, this::checkEligibility));
        registry.register(new ToolRegistry.Definition("create_refund_request",
                "提交退款申请（不可逆，需人工审批），参数 {orderNo, reason?, amount?, idempotencyKey?}。",
                ToolRisk.IRREVERSIBLE, AGENTS, this::createRefund));
    }

    private ToolResult checkEligibility(Map<String, Object> args, ToolContext context) {
        String orderNo = ToolContext.str(args, "orderNo", "LATEST");
        RefundService.Eligibility eligibility = refundService.checkEligibility(context.userId(), orderNo);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("eligible", eligibility.eligible());
        data.put("reason", eligibility.reason());
        data.put("orderNo", eligibility.orderNo());
        data.put("orderStatus", eligibility.orderStatus());
        data.put("maxAmount", eligibility.maxAmount());
        String summary = eligibility.eligible()
                ? "订单 " + eligibility.orderNo() + " 可退款，最多可退 ¥" + eligibility.maxAmount()
                : "订单 " + eligibility.orderNo() + " 不可退款：" + eligibility.reason();
        return eligibility.eligible() ? ToolResult.ok(summary, data) : ToolResult.fail(summary);
    }

    private ToolResult createRefund(Map<String, Object> args, ToolContext context) {
        String orderNo = ToolContext.str(args, "orderNo", "LATEST");
        String reason = ToolContext.str(args, "reason", "用户申请退款");
        BigDecimal amount = ToolContext.decimal(args, "amount");
        String idempotencyKey = ToolContext.str(args, "idempotencyKey", null);
        RefundService.Outcome outcome = refundService.create(context.userId(), orderNo, reason, amount,
                idempotencyKey, null);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("refundId", outcome.refundId());
        data.put("refundNo", outcome.refundNo());
        data.put("status", outcome.status());
        data.put("replayed", outcome.replayed());
        return ToolResult.ok("退款申请已受理，退款单号 " + outcome.refundNo() + "，状态 " + outcome.status(),
                data);
    }
}
