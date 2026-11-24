package com.xingtu.agent.hitl;

// ═══════ 文件级能力标注 ═══════
// [CAP-10] 人机协作 HITL
// 职责：需要人工审批时中断 Agent 循环
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import java.util.Map;

/**
 * 需要人工审批时中断 Agent 循环。由 SseEmitterSink 转成 approval 事件，
 * 审批通过后由 ApprovalService / RefundConsumer 继续执行不可逆动作。
 */
public class ApprovalRequiredException extends RuntimeException {

    private final long approvalId;
    private final String actionType;
    private final String title;
    private final Map<String, Object> detail;
    private final String risk;
    private final String expiresAt;

    public ApprovalRequiredException(long approvalId, String actionType, String title,
                                     Map<String, Object> detail, String risk, String expiresAt) {
        super("需要人工审批: " + title);
        this.approvalId = approvalId;
        this.actionType = actionType;
        this.title = title;
        this.detail = detail;
        this.risk = risk;
        this.expiresAt = expiresAt;
    }

    public long getApprovalId() {
        return approvalId;
    }

    public String getActionType() {
        return actionType;
    }

    public String getTitle() {
        return title;
    }

    public Map<String, Object> getDetail() {
        return detail;
    }

    public String getRisk() {
        return risk;
    }

    public String getExpiresAt() {
        return expiresAt;
    }
}
