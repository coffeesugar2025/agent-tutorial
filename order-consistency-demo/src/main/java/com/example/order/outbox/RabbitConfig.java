package com.example.order.outbox;

import org.springframework.amqp.core.AcknowledgeMode;
import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.rabbit.config.SimpleRabbitListenerContainerFactory;
import org.springframework.amqp.rabbit.connection.CachingConnectionFactory;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 拓扑：一个 durable topic exchange，按 eventType 作 routingKey 绑到各自队列。
 * 新增事件类型必须同时加一条 Binding，否则 mandatory 消息会被 return（Outbox 会重试并告警）。
 */
@Configuration
public class RabbitConfig {

    @Bean
    public TopicExchange orderExchange(@Value("${app.rabbit.exchange}") String name) {
        return new TopicExchange(name, true, false);
    }

    @Bean
    public Queue orderCreatedQueue(@Value("${app.rabbit.queue-created}") String name) {
        return QueueBuilder.durable(name).build();
    }

    @Bean
    public Queue orderPaidQueue(@Value("${app.rabbit.queue-paid}") String name) {
        return QueueBuilder.durable(name).build();
    }

    @Bean
    public Binding createdBinding(@Qualifier("orderCreatedQueue") Queue queue,
                                  TopicExchange orderExchange) {
        return BindingBuilder.bind(queue).to(orderExchange).with("ORDER_CREATED");
    }

    @Bean
    public Binding paidBinding(@Qualifier("orderPaidQueue") Queue queue,
                               TopicExchange orderExchange) {
        return BindingBuilder.bind(queue).to(orderExchange).with("ORDER_PAID");
    }

    /** 专供 Outbox 使用的模板：开启 mandatory，并把 confirm/return 汇入 PublishTracker */
    @Bean("outboxRabbitTemplate")
    public RabbitTemplate outboxRabbitTemplate(ConnectionFactory cf, PublishTracker tracker) {
        // 双保险：不依赖 yaml 属性名是否生效，直接在连接工厂层打开
        if (cf instanceof CachingConnectionFactory ccf) {
            ccf.setPublisherConfirmType(CachingConnectionFactory.ConfirmType.CORRELATED);
            ccf.setPublisherReturns(true);
        }
        RabbitTemplate template = new RabbitTemplate(cf);
        template.setMandatory(true);

        template.setConfirmCallback((correlationData, ack, cause) -> {
            if (correlationData != null && correlationData.getId() != null) {
                tracker.markConfirmed(correlationData.getId(), ack, cause);
            }
        });

        template.setReturnsCallback(returned -> {
            Object id = returned.getMessage().getMessageProperties().getHeader("outboxId");
            if (id != null) {
                tracker.markReturned(id.toString(),
                        "reply=" + returned.getReplyCode() + "/" + returned.getReplyText()
                                + " exchange=" + returned.getExchange()
                                + " routingKey=" + returned.getRoutingKey());
            }
        });

        return template;
    }

    /** 消费端手动 ack：由监听器自己决定 ack / nack，避免自动 ack 在业务失败时丢消息 */
    @Bean("manualAckContainerFactory")
    public SimpleRabbitListenerContainerFactory manualAckContainerFactory(ConnectionFactory cf) {
        SimpleRabbitListenerContainerFactory factory = new SimpleRabbitListenerContainerFactory();
        factory.setConnectionFactory(cf);
        factory.setAcknowledgeMode(AcknowledgeMode.MANUAL);
        factory.setPrefetchCount(10);
        return factory;
    }
}
