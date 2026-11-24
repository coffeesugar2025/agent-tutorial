package com.xingtu.agent.memory;

// ═══════ 文件级能力标注 ═══════
// [CAP-07] 记忆
// 职责：短期记忆：会话窗口（最近 N 条 user/assistant 消息），必要时叠加滚动摘要
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.repo.MessageRepository;
import com.xingtu.agent.llm.LlmProvider;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 短期记忆：会话窗口（最近 N 条 user/assistant 消息），必要时叠加滚动摘要。
 */
@Component
public class SessionMemory {

    private final MessageRepository messageRepository;
    private final AppProperties props;

    public SessionMemory(MessageRepository messageRepository, AppProperties props) {
        this.messageRepository = messageRepository;
        this.props = props;
    }

    public List<LlmProvider.Message> window(long sessionId) {
        return window(sessionId, props.getAgent().getMemoryWindow());
    }

    public List<LlmProvider.Message> window(long sessionId, int limit) {
        List<LlmProvider.Message> messages = new ArrayList<>();
        for (MessageRepository.MessageRow row : messageRepository.recent(sessionId,
                Math.max(1, limit))) {
            if ("user".equals(row.role())) {
                messages.add(LlmProvider.Message.user(row.content() == null ? "" : row.content()));
            } else if ("assistant".equals(row.role())) {
                messages.add(LlmProvider.Message.assistant(row.content() == null ? "" : row.content()));
            }
        }
        return messages;
    }

    public String transcript(long sessionId, int limit) {
        StringBuilder sb = new StringBuilder();
        for (LlmProvider.Message message : window(sessionId, limit)) {
            sb.append("user".equals(message.role()) ? "用户: " : "助手: ")
                    .append(message.content())
                    .append('\n');
        }
        return sb.toString();
    }
}
