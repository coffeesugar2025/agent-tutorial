package com.example.order.outbox;

/** 投递给消息中间件的一条消息，outboxId 同时作为 CorrelationData.id 与消费端幂等键 */
public record OutboxMessage(
        Long outboxId,
        String aggregateType,
        String aggregateId,
        String eventType,
        String payload
) {
}
