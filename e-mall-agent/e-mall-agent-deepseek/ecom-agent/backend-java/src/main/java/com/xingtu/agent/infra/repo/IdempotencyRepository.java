package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：幂等记录访问（idempotency_record），主键 idem_key
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 幂等记录访问（idempotency_record），主键 idem_key。
 */
@Repository
public class IdempotencyRepository {

    public record IdemRow(String idemKey, String scope, String resultJson, LocalDateTime createdAt,
                          LocalDateTime expiresAt) {
    }

    private final JdbcTemplate jdbc;

    public IdempotencyRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public IdemRow find(String idemKey) {
        if (idemKey == null || idemKey.isBlank()) {
            return null;
        }
        return JdbcSupport.one(jdbc,
                "SELECT idem_key, scope, result, created_at, expires_at FROM idempotency_record "
                        + "WHERE idem_key = ?",
                (rs, rowNum) -> new IdemRow(
                        JdbcSupport.str(rs, "idem_key"),
                        JdbcSupport.str(rs, "scope"),
                        JdbcSupport.str(rs, "result"),
                        JdbcSupport.time(rs, "created_at"),
                        JdbcSupport.time(rs, "expires_at")),
                idemKey);
    }

    public void save(String idemKey, String scope, String resultJson, LocalDateTime expiresAt) {
        JdbcSupport.update(jdbc,
                "INSERT INTO idempotency_record (idem_key, scope, result, expires_at) VALUES (?, ?, ?, ?) "
                        + "ON DUPLICATE KEY UPDATE result = VALUES(result), expires_at = VALUES(expires_at)",
                idemKey, scope, resultJson, expiresAt);
    }

    public List<IdemRow> listByScope(String scope, int limit) {
        return JdbcSupport.list(jdbc,
                "SELECT idem_key, scope, result, created_at, expires_at FROM idempotency_record "
                        + "WHERE scope = ? ORDER BY created_at DESC LIMIT ?",
                (rs, rowNum) -> new IdemRow(
                        JdbcSupport.str(rs, "idem_key"),
                        JdbcSupport.str(rs, "scope"),
                        JdbcSupport.str(rs, "result"),
                        JdbcSupport.time(rs, "created_at"),
                        JdbcSupport.time(rs, "expires_at")),
                scope, limit);
    }
}
