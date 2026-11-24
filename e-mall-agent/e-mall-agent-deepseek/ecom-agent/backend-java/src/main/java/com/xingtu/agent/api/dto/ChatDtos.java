package com.xingtu.agent.api.dto;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  （支撑）
// 职责：会话、消息、审批相关 DTO（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import java.util.List;
import java.util.Map;

/**
 * 会话、消息、审批相关 DTO（docs/03-API契约.md 第 2 节）。
 *
 * <p>toolCalls / citations 的持久化 JSON 里可能含额外字段（risk、latencyMs 等），
 * JsonUtil 的 ObjectMapper 已关闭 FAIL_ON_UNKNOWN_PROPERTIES，可直接反序列化到这里的 VO。</p>
 */
public final class ChatDtos {

    private ChatDtos() {
    }

    /** POST /api/v1/chat/sessions 请求体（title 可选）。 */
    public record SessionCreateReq(String title) {
    }

    /** 会话视图。 */
    public record SessionVO(long id, String title, String agentType, String status,
                            String lastMessageAt, String createdAt) {
    }

    /** 消息内的工具调用摘要（契约字段：callId / name / args / ok / summary）。 */
    public record ToolCallVO(String callId, String name, Map<String, Object> args, boolean ok,
                             String summary) {
    }

    /** 消息内的引用（与 SSE citation 事件同构）。 */
    public record CitationVO(long docId, long chunkId, String title, String snippet, double score) {
    }

    /** 消息视图。 */
    public record MessageVO(long id, String role, String content, String agentType,
                            List<ToolCallVO> toolCalls, List<CitationVO> citations, int tokenIn,
                            int tokenOut, int costCents, String createdAt) {
    }

    /** POST /api/v1/chat/stream 请求体。 */
    public record ChatStreamReq(long sessionId, String message, String clientMsgId) {
    }

    /** 中断响应 data。 */
    public record InterruptVO(boolean interrupted) {
    }

    /** 审批任务视图。 */
    public record ApprovalVO(long id, long sessionId, String actionType, String title,
                             Map<String, Object> detail, String risk, String status, String createdAt,
                             String expiresAt) {
    }

    /** POST /api/v1/chat/approvals/{approvalId} 请求体。 */
    public record ApprovalDecisionReq(String decision, String comment) {
    }

    /** 审批决策响应 data。 */
    public record ApprovalDecisionVO(long id, String status, Map<String, Object> result) {
    }
}
