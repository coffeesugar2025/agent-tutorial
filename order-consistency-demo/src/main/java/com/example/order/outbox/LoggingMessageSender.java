package com.example.order.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/** 不连 broker 的降级实现：-Doutbox.sender=log 时启用，便于本地跑单测 */
@Component
@ConditionalOnProperty(prefix = "outbox", name = "sender", havingValue = "log")
public class LoggingMessageSender implements MessageSender {

    private static final Logger log = LoggerFactory.getLogger(LoggingMessageSender.class);

    @Override
    public void send(OutboxMessage m) {
        log.info("[outbox/log] exchange=order.exchange routingKey={} outboxId={} payload={}",
                m.eventType(), m.outboxId(), m.payload());
    }
}
