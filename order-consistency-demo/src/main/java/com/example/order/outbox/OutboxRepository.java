package com.example.order.outbox;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

/**
 * 必须在业务事务内调用，不自己开事务。
 * 写订单、扣库存、插 Outbox 三件事共用同一个 DataSourceTransactionManager。
 */
@Repository
public class OutboxRepository {

    private final JdbcTemplate jdbc;
    private final ObjectMapper om;

    public OutboxRepository(JdbcTemplate jdbc, ObjectMapper om) {
        this.jdbc = jdbc;
        this.om = om;
    }

    public void append(String aggregateType, String aggregateId, String eventType, Object payload) {
        try {
            jdbc.update("""
                    INSERT INTO t_outbox_event(aggregate_type, aggregate_id, event_type, payload, status)
                    VALUES (?, ?, ?, ?, 'PENDING')
                    """, aggregateType, aggregateId, eventType, om.writeValueAsString(payload));
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException(e);
        }
    }
}
