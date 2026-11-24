package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：会话中断登记：POST /chat/sessions/{id}/interrupt 置标记，Agent 循环在每步开始前
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 会话中断登记：POST /chat/sessions/{id}/interrupt 置标记，Agent 循环在每步开始前检查。
 */
@Component
public class InterruptRegistry {

    private final Map<Long, Boolean> flags = new ConcurrentHashMap<>();

    public void interrupt(long sessionId) {
        flags.put(sessionId, Boolean.TRUE);
    }

    public boolean isInterrupted(long sessionId) {
        return Boolean.TRUE.equals(flags.get(sessionId));
    }

    public void clear(long sessionId) {
        flags.remove(sessionId);
    }

    public int size() {
        return flags.size();
    }
}
