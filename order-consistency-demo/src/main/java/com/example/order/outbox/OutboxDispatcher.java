package com.example.order.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.util.Collections;
import java.util.List;

/**
 * 事务外投递，天然是 at-least-once。
 * 抢占（SELECT FOR UPDATE SKIP LOCKED + 标记 PROCESSING）在同一个短事务里完成，
 * 避免多实例在「查询提交后、标记前」的窗口重复捞同一批。
 */
@Component
public class OutboxDispatcher {

    private static final Logger log = LoggerFactory.getLogger(OutboxDispatcher.class);

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final MessageSender sender;

    public OutboxDispatcher(JdbcTemplate jdbc, PlatformTransactionManager tm, MessageSender sender) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(tm);
        this.sender = sender;
    }

    @Scheduled(fixedDelayString = "${outbox.poll-ms:500}")
    public void dispatch() {
        List<OutboxRow> batch = tx.execute(status -> {
            List<OutboxRow> rows = jdbc.query("""
                    SELECT id, aggregate_type, aggregate_id, event_type, payload, retry_count
                      FROM t_outbox_event
                     WHERE (status = 'PENDING' AND next_retry_at <= CURRENT_TIMESTAMP(3))
                        OR (status = 'PROCESSING' AND locked_at IS NOT NULL
                            AND locked_at < DATE_SUB(CURRENT_TIMESTAMP(3), INTERVAL 30 SECOND))
                     ORDER BY created_at
                     LIMIT 100
                     FOR UPDATE SKIP LOCKED
                    """, (rs, n) -> new OutboxRow(
                            rs.getLong("id"),
                            rs.getString("aggregate_type"),
                            rs.getString("aggregate_id"),
                            rs.getString("event_type"),
                            rs.getString("payload"),
                            rs.getInt("retry_count")));

            if (rows.isEmpty()) {
                return rows;
            }
            String marks = String.join(",", Collections.nCopies(rows.size(), "?"));
            jdbc.update("UPDATE t_outbox_event SET status='PROCESSING', " +
                            "locked_at=CURRENT_TIMESTAMP(3) WHERE id IN (" + marks + ")",
                    rows.stream().map(OutboxRow::id).toArray());
            return rows;
        });

        if (batch == null || batch.isEmpty()) {
            return;
        }

        // 网络调用放在事务外：不把数据库行锁压在 broker 延迟上
        for (OutboxRow r : batch) {
            try {
                sender.send(new OutboxMessage(
                        r.id(), r.aggregateType(), r.aggregateId(), r.eventType(), r.payload()));
                jdbc.update("UPDATE t_outbox_event SET status='SENT', locked_at=NULL WHERE id=?", r.id());
            } catch (Exception e) {
                if (e instanceof InterruptedException) {
                    Thread.currentThread().interrupt();
                }
                long backoff = Math.min(60L, 1L << Math.min(r.retryCount(), 6)); // 1,2,4..60 秒
                jdbc.update("""
                        UPDATE t_outbox_event
                           SET status='PENDING', locked_at=NULL, retry_count=retry_count+1,
                               next_retry_at = DATE_ADD(CURRENT_TIMESTAMP(3), INTERVAL ? SECOND)
                         WHERE id=?
                        """, backoff, r.id());
                log.warn("[outbox] send failed id={} eventType={} retry={}",
                        r.id(), r.eventType(), r.retryCount() + 1, e);
            }
        }
    }

    public record OutboxRow(Long id, String aggregateType, String aggregateId,
                            String eventType, String payload, int retryCount) {
    }
}
