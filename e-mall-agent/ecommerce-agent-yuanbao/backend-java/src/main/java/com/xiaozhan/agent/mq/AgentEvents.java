package com.xiaozhan.agent.mq;

import org.springframework.amqp.core.*;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;

import java.util.Map;

/** 3.9 / 3.10：长任务、审计、RAG 增量索引三类事件走 RabbitMQ topic。 */
@Configuration
public class AgentEvents {
    @Bean TopicExchange agentTopic() { return new TopicExchange("agent.topic", true, false); }
    @Bean Queue longTaskQueue() { return QueueBuilder.durable("agent.longtask").build(); }
    @Bean Queue auditQueue() { return QueueBuilder.durable("agent.audit").build(); }
    @Bean Queue ragIndexQueue() { return QueueBuilder.durable("agent.ragindex").build(); }
    @Bean Binding bindTask(TopicExchange e, Queue longTaskQueue) {
        return BindingBuilder.bind(longTaskQueue).to(e).with("task.#"); }
    @Bean Binding bindAudit(TopicExchange e, Queue auditQueue) {
        return BindingBuilder.bind(auditQueue).to(e).with("audit.#"); }
    @Bean Binding bindRag(TopicExchange e, Queue ragIndexQueue) {
        return BindingBuilder.bind(ragIndexQueue).to(e).with("rag.#"); }

    @Component
    public static class Publisher {
        private final RabbitTemplate tpl;
        public Publisher(RabbitTemplate tpl) { this.tpl = tpl; }
        public void longTask(String taskId) {
            tpl.convertAndSend("agent.topic", "task.start", Map.of("task_id", taskId, "at", System.currentTimeMillis()));
        }
        public void audit(String traceId, String tool) {
            tpl.convertAndSend("agent.topic", "audit.call", Map.of("trace_id", traceId, "tool", tool));
        }
        public void ragIndex(String docId, int version) {
            tpl.convertAndSend("agent.topic", "rag.upsert", Map.of("doc_id", docId, "version", version));
        }
    }

    @Component
    public static class Consumer {
        @RabbitListener(queues = "agent.ragindex")
        public void onRagIndex(Map<String, Object> msg) {
            // 增量索引：只处理 diff 变化的 chunk，本例仅记录，生产接 MilvusAdapter.upsert
        }
        @RabbitListener(queues = "agent.longtask")
        public void onLongTask(Map<String, Object> msg) {
            // 长任务心跳 / checkpoint 恢复
        }
    }
}
