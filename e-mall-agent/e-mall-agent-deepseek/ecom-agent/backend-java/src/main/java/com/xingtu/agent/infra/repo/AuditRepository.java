package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 审计日志访问（audit_log）：WRITE / IRREVERSIBLE 工具执行后必写。
 */
@Repository
public class AuditRepository {

    public record AuditRow(long id, long userId, String action, String target, String detailJson, String ip,
                           LocalDateTime createdAt) {
    }

    private final JdbcTemplate jdbc;

    public AuditRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void insert(long userId, String action, String target, String detailJson, String ip) {
        JdbcSupport.update(jdbc,
                "INSERT INTO audit_log (user_id, action, target, detail, ip) VALUES (?, ?, ?, ?, ?)",
                userId, action, target, detailJson, ip);
    }

    public List<AuditRow> listByUser(long userId, int limit) {
        return JdbcSupport.list(jdbc,
                "SELECT id, user_id, action, target, detail, ip, created_at FROM audit_log "
                        + "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                mapper(), userId, limit);
    }

    private RowMapper<AuditRow> mapper() {
        return (rs, rowNum) -> new AuditRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.lng(rs, "user_id"),
                JdbcSupport.str(rs, "action"),
                JdbcSupport.str(rs, "target"),
                JdbcSupport.str(rs, "detail"),
                JdbcSupport.str(rs, "ip"),
                JdbcSupport.time(rs, "created_at"));
    }
}
