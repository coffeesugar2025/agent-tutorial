package com.example.order.idem;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.function.Supplier;

/**
 * 幂等守卫：幂等记录与业务写在同一事务内。
 * 业务失败整体回滚、key 自动释放；并发重复请求被主键冲突挡住并串行化，
 * 第二个请求读到第一个请求提交后的响应快照。
 */
@Component
public class IdempotencyGuard {

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final ObjectMapper om;

    public IdempotencyGuard(JdbcTemplate jdbc, PlatformTransactionManager tm, ObjectMapper om) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(tm);
        this.om = om;
    }

    /** 相同 key + 相同 body → 返回首次结果；相同 key + 不同 body → 400；首次仍在处理 → 409 */
    public <T> T execute(String key, Object request, Class<T> responseType, Supplier<T> biz) {
        String hash = sha256(writeJson(request));

        return tx.execute(status -> {
            try {
                jdbc.update("""
                        INSERT INTO t_idempotency(idem_key, request_hash, status)
                        VALUES (?, ?, 'IN_PROGRESS')
                        """, key, hash);
            } catch (DuplicateKeyException e) {
                return readExisting(key, hash, responseType);
            }

            // 业务执行 + 回写响应快照：与上面的 INSERT 共用一个事务
            T result = biz.get();
            jdbc.update("UPDATE t_idempotency SET status='SUCCEEDED', response_json=? WHERE idem_key=?",
                    writeJson(result), key);
            return result;
        });
    }

    private <T> T readExisting(String key, String hash, Class<T> type) {
        return jdbc.queryForObject("""
                SELECT request_hash, status, response_json FROM t_idempotency WHERE idem_key=?
                """, (rs, n) -> {
                    if (!hash.equals(rs.getString("request_hash"))) {
                        throw new IllegalArgumentException("Idempotency-Key reused with different payload");
                    }
                    if (!"SUCCEEDED".equals(rs.getString("status"))) {
                        throw new IdempotentInProgressException(key);
                    }
                    try {
                        return om.readValue(rs.getString("response_json"), type);
                    } catch (JsonProcessingException e) {
                        throw new IllegalStateException(e);
                    }
                }, key);
    }

    private String sha256(String s) {
        try {
            return HexFormat.of().formatHex(
                    MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    private String writeJson(Object o) {
        try {
            return om.writeValueAsString(o);
        } catch (JsonProcessingException e) {
            throw new IllegalArgumentException(e);
        }
    }

    public static class IdempotentInProgressException extends RuntimeException {
        public IdempotentInProgressException(String key) {
            super("request still processing: " + key);
        }
    }
}
