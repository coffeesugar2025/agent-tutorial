package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：SSE 事件出口
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import java.util.Map;

/**
 * SSE 事件出口。事件名与 data 结构与 docs/03-API契约.md 第 2 节逐字一致：
 * meta / agent / delta / tool_call / tool_result / citation / approval / usage / done / error。
 */
public interface SseEventSink {

    void meta(String traceId, long messageId, long sessionId);

    void agent(String agentType, String reason);

    void delta(String text);

    void toolCall(String callId, String name, Map<String, Object> args, String risk);

    void toolResult(String callId, String name, boolean ok, String summary, long latencyMs);

    void citation(long docId, long chunkId, String title, String snippet, double score);

    void approval(long approvalId, String title, Map<String, Object> detail, String risk,
                  String expiresAt);

    void usage(int promptTokens, int completionTokens, int costCents, String model);

    void done(long messageId, String finishReason);

    void error(int code, String message);

    boolean isClosed();
}
