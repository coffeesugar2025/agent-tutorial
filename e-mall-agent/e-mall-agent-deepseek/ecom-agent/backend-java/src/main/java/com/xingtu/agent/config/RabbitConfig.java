package com.xingtu.agent.config;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.DirectExchange;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * RabbitMQ 拓扑：topic exchange ecom.agent + 5 个业务队列 + 死信队列。
 * 队列名与路由键同名（契约第 8 节），死信统一进 ecom.agent.dlx。
 */
@Configuration
@ConditionalOnProperty(prefix = "app.mq", name = "enabled", havingValue = "true", matchIfMissing = true)
public class RabbitConfig {

    public static final String QUEUE_KNOWLEDGE_INDEX = "ecom.agent.knowledge.index";
    public static final String QUEUE_KNOWLEDGE_DELETE = "ecom.agent.knowledge.delete";
    public static final String QUEUE_SESSION_SUMMARIZE = "ecom.agent.session.summarize";
    public static final String QUEUE_REFUND_EXECUTE = "ecom.agent.refund.execute";
    public static final String QUEUE_EVAL_BATCH = "ecom.agent.eval.batch";

    @Bean
    public TopicExchange agentExchange(AppProperties props) {
        return new TopicExchange(props.getMq().getExchange(), true, false);
    }

    @Bean
    public DirectExchange deadLetterExchange(AppProperties props) {
        return new DirectExchange(props.getMq().getDlx(), true, false);
    }

    @Bean
    public MessageConverter jacksonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    @Bean
    public Queue knowledgeIndexQueue(AppProperties props) {
        return deadLetterQueue(QUEUE_KNOWLEDGE_INDEX, props);
    }

    @Bean
    public Queue knowledgeDeleteQueue(AppProperties props) {
        return deadLetterQueue(QUEUE_KNOWLEDGE_DELETE, props);
    }

    @Bean
    public Queue sessionSummarizeQueue(AppProperties props) {
        return deadLetterQueue(QUEUE_SESSION_SUMMARIZE, props);
    }

    @Bean
    public Queue refundExecuteQueue(AppProperties props) {
        return deadLetterQueue(QUEUE_REFUND_EXECUTE, props);
    }

    @Bean
    public Queue evalBatchQueue(AppProperties props) {
        return deadLetterQueue(QUEUE_EVAL_BATCH, props);
    }

    @Bean
    public Queue deadLetterQueue(AppProperties props) {
        return QueueBuilder.durable(props.getMq().getDlx() + ".queue").build();
    }

    @Bean
    public Binding knowledgeIndexBinding(TopicExchange agentExchange, Queue knowledgeIndexQueue) {
        return BindingBuilder.bind(knowledgeIndexQueue).to(agentExchange).with("knowledge.index");
    }

    @Bean
    public Binding knowledgeDeleteBinding(TopicExchange agentExchange, Queue knowledgeDeleteQueue) {
        return BindingBuilder.bind(knowledgeDeleteQueue).to(agentExchange).with("knowledge.delete");
    }

    @Bean
    public Binding sessionSummarizeBinding(TopicExchange agentExchange, Queue sessionSummarizeQueue) {
        return BindingBuilder.bind(sessionSummarizeQueue).to(agentExchange).with("session.summarize");
    }

    @Bean
    public Binding refundExecuteBinding(TopicExchange agentExchange, Queue refundExecuteQueue) {
        return BindingBuilder.bind(refundExecuteQueue).to(agentExchange).with("refund.execute");
    }

    @Bean
    public Binding evalBatchBinding(TopicExchange agentExchange, Queue evalBatchQueue) {
        return BindingBuilder.bind(evalBatchQueue).to(agentExchange).with("eval.batch");
    }

    private Queue deadLetterQueue(String name, AppProperties props) {
        return QueueBuilder.durable(name)
                .withArgument("x-dead-letter-exchange", props.getMq().getDlx())
                .withArgument("x-dead-letter-routing-key", name)
                .build();
    }
}
