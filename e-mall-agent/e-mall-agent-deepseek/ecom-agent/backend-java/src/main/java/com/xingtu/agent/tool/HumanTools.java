package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：人工协同工具：escalate_to_human（WRITE，执行 + 审计 + 生成工单）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.hitl.ApprovalService;
import com.xingtu.agent.infra.repo.ApprovalRepository;
import com.xingtu.agent.infra.repo.AuditRepository;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 人工协同工具：escalate_to_human（WRITE，执行 + 审计 + 生成工单）。
 * 与 IRREVERSIBLE 不同，转人工不会中断对话，只创建一张待处理工单。
 */
@Component
public class HumanTools {

    private static final List<String> AGENTS = List.of("SERVICE");

    private final ApprovalService approvalService;
    private final AuditRepository auditRepository;

    public HumanTools(ToolRegistry registry, ApprovalService approvalService,
                      AuditRepository auditRepository) {
        this.approvalService = approvalService;
        this.auditRepository = auditRepository;
        registry.register(new ToolRegistry.Definition("escalate_to_human",
                "转人工客服并生成工单，参数 {reason}；适用于投诉、复杂售后或模型无法处理的问题。",
                ToolRisk.WRITE, AGENTS, this::escalate));
    }

    private ToolResult escalate(Map<String, Object> args, ToolContext context) {
        String reason = ToolContext.str(args, "reason", context.question());
        Map<String, Object> detail = new LinkedHashMap<>();
        detail.put("reason", reason);
        detail.put("question", context.question());
        detail.put("userId", context.userId());
        ApprovalRepository.ApprovalRow row = approvalService.create(context.sessionId(), null,
                context.userId(), ApprovalService.ACTION_ESCALATE, "转人工：" + abbreviate(reason),
                detail, "WRITE");
        auditRepository.insert(context.userId(), "ESCALATE_TO_HUMAN", "approval:" + row.id(),
                JsonUtil.toJson(detail), null);
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("approvalId", row.id());
        data.put("ticketNo", "TK" + row.id());
        data.put("status", row.status());
        return ToolResult.ok("已生成人工工单 TK" + row.id() + "，客服会尽快跟进", data);
    }

    private String abbreviate(String text) {
        String single = text == null ? "" : text.replace('\n', ' ');
        return single.length() <= 40 ? single : single.substring(0, 40) + "...";
    }
}
