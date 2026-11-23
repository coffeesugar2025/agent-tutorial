package com.xingtu.agent.infra;

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.repo.AsyncTaskRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * RabbitMQ 发布器：MQ 关闭或发布失败时落 async_task 兜底（状态 QUEUED，由补偿任务处理）。
 *
 * <p>路由键与契约一致：knowledge.index / knowledge.delete / session.summarize /
 * refund.execute / eval.batch。</p>
 */
@Component
public class RabbitPublisher {

    private static final Logger log = LoggerFactory.getLogger(RabbitPublisher.class);

    public static final String RK_KNOWLEDGE_INDEX = "knowledge.index";
    public static final String RK_KNOWLEDGE_DELETE = "knowledge.delete";
    public static final String RK_SESSION_SUMMARIZE = "session.summarize";
    public static final String RK_REFUND_EXECUTE = "refund.execute";
    public static final String RK_EVAL_BATCH = "eval.batch";

    private final RabbitTemplate rabbitTemplate;
    private final AppProperties props;
    private final AsyncTaskRepository asyncTaskRepository;

    public RabbitPublisher(RabbitTemplate rabbitTemplate, AppProperties props,
                           AsyncTaskRepository asyncTaskRepository) {
        this.rabbitTemplate = rabbitTemplate;
        this.props = props;
        this.asyncTaskRepository = asyncTaskRepository;
    }

    public void publishKnowledgeIndex(long documentId, long jobId) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("documentId", documentId);
        payload.put("jobId", jobId);
        publish(RK_KNOWLEDGE_INDEX, "KNOWLEDGE_INDEX", payload);
    }

    public void publishKnowledgeDelete(long documentId, long jobId) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("documentId", documentId);
        payload.put("jobId", jobId);
        publish(RK_KNOWLEDGE_DELETE, "KNOWLEDGE_DELETE", payload);
    }

    public void publishSessionSummary(long sessionId, long upToMessageId) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("sessionId", sessionId);
        payload.put("upToMessageId", upToMessageId);
        publish(RK_SESSION_SUMMARIZE, "SESSION_SUMMARIZE", payload);
    }

    public void publishRefundExecute(long refundId, long approvalId) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("refundId", refundId);
        payload.put("approvalId", approvalId);
        publish(RK_REFUND_EXECUTE, "REFUND_EXECUTE", payload);
    }

    public void publishEvalBatch(long runId, String suite) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("runId", runId);
        payload.put("suite", suite);
        publish(RK_EVAL_BATCH, "EVAL_BATCH", payload);
    }

    public void publish(String routingKey, String taskType, Map<String, Object> payload) {
        if (!props.getMq().isEnabled()) {
            persist(taskType, payload, "MQ 已关闭");
            return;
        }
        try {
            rabbitTemplate.convertAndSend(props.getMq().getExchange(), routingKey, payload);
        } catch (AmqpException e) {
            log.warn("RabbitMQ 发布失败 routingKey={} : {}，落 async_task 兜底", routingKey, e.getMessage());
            persist(taskType, payload, e.getMessage());
        }
    }

    private void persist(String taskType, Map<String, Object> payload, String reason) {
        try {
            asyncTaskRepository.insert(taskType, JsonUtil.toJson(payload), 3);
        } catch (RuntimeException e) {
            log.error("async_task 兜底也失败 taskType={} reason={} : {}", taskType, reason, e.getMessage());
        }
    }
}
