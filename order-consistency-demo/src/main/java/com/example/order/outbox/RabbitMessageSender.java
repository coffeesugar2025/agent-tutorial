package com.example.order.outbox;

import org.springframework.amqp.AmqpException;
import org.springframework.amqp.core.Message;
import org.springframework.amqp.core.MessageDeliveryMode;
import org.springframework.amqp.core.MessageProperties;
import org.springframework.amqp.rabbit.connection.CorrelationData;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * 同步等待 publisher confirm 后才返回；任何 nack / return / 超时都抛异常，
 * OutboxDispatcher 据此把记录留在 PENDING 并退避重试 —— 这是 Outbox 不丢消息的最后一环。
 */
@Component
@ConditionalOnProperty(prefix = "outbox", name = "sender", havingValue = "rabbit", matchIfMissing = true)
public class RabbitMessageSender implements MessageSender {

    private final RabbitTemplate template;
    private final PublishTracker tracker;
    private final String exchange;
    private final long confirmTimeoutMs;

    public RabbitMessageSender(@Qualifier("outboxRabbitTemplate") RabbitTemplate template,
                               PublishTracker tracker,
                               @Value("${app.rabbit.exchange}") String exchange,
                               @Value("${outbox.confirm-timeout-ms:5000}") long confirmTimeoutMs) {
        this.template = template;
        this.tracker = tracker;
        this.exchange = exchange;
        this.confirmTimeoutMs = confirmTimeoutMs;
    }

    @Override
    public void send(OutboxMessage m) throws Exception {
        String id = String.valueOf(m.outboxId());
        CompletableFuture<String> result = tracker.register(id);
        try {
            template.send(exchange, m.eventType(), toAmqpMessage(m), new CorrelationData(id));
            String error = result.get(confirmTimeoutMs, TimeUnit.MILLISECONDS);
            if (error != null) {
                throw new AmqpException("publish failed outboxId=" + id + ": " + error);
            }
        } catch (TimeoutException e) {
            throw new AmqpException("publish confirm timeout outboxId=" + id, e);
        } finally {
            tracker.discard(id);
        }
    }

    private Message toAmqpMessage(OutboxMessage m) {
        MessageProperties props = new MessageProperties();
        props.setContentType("application/json");
        props.setDeliveryMode(MessageDeliveryMode.PERSISTENT);   // 持久化消息
        props.setMessageId(String.valueOf(m.outboxId()));
        props.setHeader("outboxId", m.outboxId());              // 消费端幂等键 / return 关联键
        props.setHeader("eventType", m.eventType());
        props.setHeader("aggregateId", m.aggregateId());
        props.setHeader("aggregateType", m.aggregateType());
        return new Message(m.payload().getBytes(StandardCharsets.UTF_8), props);
    }
}
