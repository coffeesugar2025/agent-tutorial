package com.xingtu.agent.tool;

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
