package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：工具风险分级（docs/00 第 5 节）： READ 直接执行；WRITE 执行 + 审计；IRREVERSIBLE 
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

/**
 * 工具风险分级（docs/00 第 5 节）：
 * READ 直接执行；WRITE 执行 + 审计；IRREVERSIBLE 必须人工审批后执行。
 */
public enum ToolRisk {

    READ,
    WRITE,
    IRREVERSIBLE;

    public boolean requiresApproval() {
        return this == IRREVERSIBLE;
    }

    public boolean needsAudit() {
        return this == WRITE || this == IRREVERSIBLE;
    }
}
