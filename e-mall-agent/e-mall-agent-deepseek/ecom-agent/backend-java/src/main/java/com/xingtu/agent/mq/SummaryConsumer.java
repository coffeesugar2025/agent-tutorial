package com.xingtu.agent.mq;

// ═══════ 文件级能力标注 ═══════
// [CAP-14] 可靠性/降级
// 职责：会话摘要消费者：session
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.RabbitConfig;
import com.xingtu.agent.infra.repo.AsyncTaskRepository;
import com.xingtu.agent.memory.SummaryService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 会话摘要消费者：session.summarize（契约第 8 节）。
 *
 * <p>消息窗口超过阈值时把历史对话压缩成滚动摘要写入 chat_session.summary，
 * 摘要失败时 SummaryService 内部会退化为抽取式摘要，因此这里不会因此抛错。</p>
 */
@Component
@ConditionalOnProperty(prefix = "app.mq", name = "enabled", havingValue = "true", matchIfMissing = true)
public class SummaryConsumer {

    private static final Logger log = LoggerFactory.getLogger(SummaryConsumer.class);

    private final SummaryService summaryService;
    private final AsyncTaskRepository asyncTaskRepository;

    public SummaryConsumer(SummaryService summaryService, AsyncTaskRepository asyncTaskRepository) {
        this.summaryService = summaryService;
        this.asyncTaskRepository = asyncTaskRepository;
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_SESSION_SUMMARIZE)
    public void onSummarize(Object payload) {
        Map<String, Object> data = MqSupport.toMap(payload);
        long sessionId = MqSupport.longValue(data, "sessionId");
        long upToMessageId = MqSupport.longValue(data, "upToMessageId");
        MqSupport.retry("SESSION_SUMMARIZE", data, asyncTaskRepository, log,
                () -> summarize(sessionId, upToMessageId));
    }

    private void summarize(long sessionId, long upToMessageId) {
        if (sessionId <= 0) {
            throw new IllegalArgumentException("sessionId 缺失");
        }
        String summary = summaryService.summarize(sessionId, upToMessageId);
        if (summary == null || summary.isBlank()) {
            log.info("会话无可摘要内容，跳过 sessionId={} upToMessageId={}", sessionId, upToMessageId);
            return;
        }
        log.info("会话摘要完成 sessionId={} length={}", sessionId, summary.length());
    }
}
