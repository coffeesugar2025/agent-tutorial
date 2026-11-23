package com.xingtu.agent.memory;

import com.xingtu.agent.infra.repo.MessageRepository;
import com.xingtu.agent.infra.repo.SessionRepository;
import com.xingtu.agent.llm.LlmProvider;
import com.xingtu.agent.llm.ModelRouter;
import com.xingtu.agent.security.PiiMasker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 会话滚动摘要：消息超过阈值时用 LLM 压缩成一句话摘要，失败时退化为抽取式摘要。
 * 摘要写入 chat_session.summary，下一轮对话注入 prompt，控制上下文长度。
 */
@Component
public class SummaryService {

    private static final Logger log = LoggerFactory.getLogger(SummaryService.class);

    private final SessionRepository sessionRepository;
    private final MessageRepository messageRepository;
    private final ModelRouter modelRouter;
    private final PiiMasker piiMasker;

    public SummaryService(SessionRepository sessionRepository, MessageRepository messageRepository,
                          ModelRouter modelRouter, PiiMasker piiMasker) {
        this.sessionRepository = sessionRepository;
        this.messageRepository = messageRepository;
        this.modelRouter = modelRouter;
        this.piiMasker = piiMasker;
    }

    public String summarize(long sessionId, long upToMessageId) {
        List<MessageRepository.MessageRow> rows = new ArrayList<>();
        for (MessageRepository.MessageRow row : messageRepository.recent(sessionId, 60)) {
            if (upToMessageId <= 0 || row.id() <= upToMessageId) {
                rows.add(row);
            }
        }
        if (rows.isEmpty()) {
            return null;
        }
        String transcript = renderTranscript(rows);
        String summary = llmSummary(transcript);
        if (summary == null || summary.isBlank()) {
            summary = extractiveSummary(rows);
        }
        sessionRepository.updateSummary(sessionId, summary);
        return summary;
    }

    private String llmSummary(String transcript) {
        try {
            List<LlmProvider.Message> messages = new ArrayList<>();
            messages.add(LlmProvider.Message.system(
                    "你是会话摘要器。用不超过 120 字概括用户诉求、已确认的事实与待办，"
                            + "不要编造，不要输出 JSON。"));
            messages.add(LlmProvider.Message.user("对话记录：\n" + piiMasker.maskAll(transcript)));
            LlmProvider.Result result = modelRouter.chat(messages);
            return result.text();
        } catch (RuntimeException e) {
            log.debug("LLM 摘要失败，使用抽取式摘要: {}", e.getMessage());
            return null;
        }
    }

    private String extractiveSummary(List<MessageRepository.MessageRow> rows) {
        StringBuilder sb = new StringBuilder();
        int taken = 0;
        for (int i = rows.size() - 1; i >= 0 && taken < 3; i--) {
            MessageRepository.MessageRow row = rows.get(i);
            if (!"user".equals(row.role())) {
                continue;
            }
            String content = row.content() == null ? "" : row.content().replace('\n', ' ');
            if (content.length() > 60) {
                content = content.substring(0, 60) + "…";
            }
            sb.append(content).append(" / ");
            taken++;
        }
        String summary = sb.length() == 0 ? "（无有效内容）" : sb.toString();
        return summary.length() <= 200 ? summary : summary.substring(0, 200);
    }

    private String renderTranscript(List<MessageRepository.MessageRow> rows) {
        StringBuilder sb = new StringBuilder();
        for (MessageRepository.MessageRow row : rows) {
            if (!"user".equals(row.role()) && !"assistant".equals(row.role())) {
                continue;
            }
            sb.append("user".equals(row.role()) ? "用户: " : "助手: ")
                    .append(row.content() == null ? "" : row.content())
                    .append('\n');
        }
        return sb.toString();
    }
}
