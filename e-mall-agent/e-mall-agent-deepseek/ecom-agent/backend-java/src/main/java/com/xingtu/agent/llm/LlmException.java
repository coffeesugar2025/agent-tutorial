package com.xingtu.agent.llm;

// ═══════ 文件级能力标注 ═══════
// [CAP-02] 模型接入与输出控制  |  [CAP-18] 成本与模型工程
// 职责：单次模型调用失败（网络 / 4xx / 5xx / 解析失败），由 ModelRouter 捕获触发降级
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

/**
 * 单次模型调用失败（网络 / 4xx / 5xx / 解析失败），由 ModelRouter 捕获触发降级。
 */
public class LlmException extends RuntimeException {

    public LlmException(String message) {
        super(message);
    }

    public LlmException(String message, Throwable cause) {
        super(message, cause);
    }
}
