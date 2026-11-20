package com.example.order.outbox;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.rabbitmq.client.Channel;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * Outbox 是 at-least-once：confirm 超时重投、消费失败 requeue 都会造成重复消息。
 * 这里用 t_consumed_event(outbox_id) 做幂等，再手动 ack。
 */
@Component
public class OrderEventConsumer {

    private static final Logger log = LoggerFactory.getLogger(OrderEventConsumer.class);

    private final JdbcTemplate jdbc;
    private final ObjectMapper om;

    public OrderEventConsumer(JdbcTemplate jdbc, ObjectMapper om) {
        this.jdbc = jdbc;
        this.om = om;
    }

    @RabbitListener(queues = "${app.rabbit.queue-created}", containerFactory = "manualAckContainerFactory")
    public void onOrderCreated(Message message, Channel channel) throws IOException {
        consume("ORDER_CREATED", message, channel, message.getMessageProperties().getDeliveryTag());
    }

    @RabbitListener(queues = "${app.rabbit.queue-paid}", containerFactory = "manualAckContainerFactory")
    public void onOrderPaid(Message message, Channel channel) throws IOException {
        consume("ORDER_PAID", message, channel, message.getMessageProperties().getDeliveryTag());
    }

    private void consume(String expectedType, Message message, Channel channel, long tag) throws IOException {
        EventHeaders h = headersOf(message);
        try {
            if (h.outboxId() == null) {
                log.error("[consumer] missing outboxId header, drop. type={}", expectedType);
                channel.basicAck(tag, false);   // 毒消息直接确认，避免无限 requeue
                return;
            }

            int inserted = jdbc.update(
                    "INSERT IGNORE INTO t_consumed_event(outbox_id, event_type) VALUES (?, ?)",
                    h.outboxId(), h.eventType());

            if (inserted == 1) {
                String payload = new String(message.getBody(), StandardCharsets.UTF_8);
                JsonNode event = om.readTree(payload);  // 真实业务在这里反序列化并处理读模型
                log.info("[consumer] handled type={} outboxId={} aggregateId={} event={}",
                        h.eventType(), h.outboxId(), h.aggregateId(), event);
                // 生产环境：把「业务处理」与上面的 INSERT 放进同一个 @Transactional，
                // 才能保证处理一次且仅一次；本示例只做日志演示。
            } else {
                log.info("[consumer] duplicate skipped outboxId={}", h.outboxId());
            }
            channel.basicAck(tag, false);
        } catch (Exception e) {
            log.warn("[consumer] handle failed, requeue. type={}", expectedType, e);
            channel.basicNack(tag, false, true);
        }
    }

    private EventHeaders headersOf(Message message) {
        var p = message.getMessageProperties();
        Object id = p.getHeader("outboxId");
        return new EventHeaders(
                id == null ? null : Long.valueOf(id.toString()),
                str(p.getHeader("eventType")),
                str(p.getHeader("aggregateId")));
    }

    private String str(Object o) {
        return o == null ? null : o.toString();
    }

    private record EventHeaders(Long outboxId, String eventType, String aggregateId) {
    }
}
