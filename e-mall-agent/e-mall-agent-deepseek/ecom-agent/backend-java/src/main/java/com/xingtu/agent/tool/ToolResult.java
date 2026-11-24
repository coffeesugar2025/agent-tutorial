package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：工具执行结果：summary 会进入 SSE tool_result 与 prompt，data 只回给调用方（不直接进
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.rag.Citation;

import java.util.List;
import java.util.Map;

/**
 * 工具执行结果：summary 会进入 SSE tool_result 与 prompt，data 只回给调用方（不直接进 prompt）。
 */
public record ToolResult(boolean ok, String summary, Object data, List<Citation> citations,
                         long latencyMs) {

    public static ToolResult ok(String summary, Object data) {
        return new ToolResult(true, summary, data, List.of(), 0L);
    }

    public static ToolResult ok(String summary, Object data, List<Citation> citations) {
        return new ToolResult(true, summary, data, citations == null ? List.of() : citations, 0L);
    }

    public static ToolResult fail(String summary) {
        return new ToolResult(false, summary, null, List.of(), 0L);
    }

    public ToolResult withLatency(long millis) {
        return new ToolResult(ok, summary, data, citations, millis);
    }

    public String dataJson() {
        return JsonUtil.toJsonOrNull(data);
    }

    public Map<String, Object> dataMap() {
        return JsonUtil.toMap(data);
    }

    public String promptLine() {
        return "TOOL_RESULT ok=" + ok + " summary=" + summary;
    }
}
