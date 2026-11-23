package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 模型调用账单访问（llm_call），成本统计的唯一事实源。
 */
@Repository
public class LlmCallRepository {

    public record ModelAgg(String model, String provider, long calls, long costCents, long avgLatencyMs) {
    }

    public record ProviderAgg(String provider, long calls, long costCents) {
    }

    public record DailyAgg(String date, long calls, long costCents) {
    }

    private final JdbcTemplate jdbc;

    public LlmCallRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void insert(String traceId, String spanId, String provider, String model, int promptTokens,
                       int completionTokens, int cachedTokens, int costCents, int latencyMs, String status) {
        JdbcSupport.update(jdbc,
                "INSERT INTO llm_call (trace_id, span_id, provider, model, prompt_tokens, completion_tokens, "
                        + "cached_tokens, cost_cents, latency_ms, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                traceId, spanId, provider, model, promptTokens, completionTokens, cachedTokens, costCents,
                latencyMs, status);
    }

    public long sumCostSince(LocalDateTime since) {
        Long value = jdbc.queryForObject(
                "SELECT COALESCE(SUM(cost_cents), 0) FROM llm_call WHERE created_at >= ?",
                Long.class, since);
        return value == null ? 0L : value;
    }

    public long countSince(LocalDateTime since) {
        return JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM llm_call WHERE created_at >= ?", since);
    }

    public long sumPromptTokensSince(LocalDateTime since) {
        Long value = jdbc.queryForObject(
                "SELECT COALESCE(SUM(prompt_tokens), 0) FROM llm_call WHERE created_at >= ?",
                Long.class, since);
        return value == null ? 0L : value;
    }

    public long sumCompletionTokensSince(LocalDateTime since) {
        Long value = jdbc.queryForObject(
                "SELECT COALESCE(SUM(completion_tokens), 0) FROM llm_call WHERE created_at >= ?",
                Long.class, since);
        return value == null ? 0L : value;
    }

    public List<ModelAgg> byModel(LocalDateTime since, int limit) {
        return JdbcSupport.list(jdbc,
                "SELECT model, provider, COUNT(*) AS calls, COALESCE(SUM(cost_cents), 0) AS cost, "
                        + "COALESCE(AVG(latency_ms), 0) AS avg_latency FROM llm_call WHERE created_at >= ? "
                        + "GROUP BY model, provider ORDER BY cost DESC LIMIT ?",
                (rs, rowNum) -> new ModelAgg(
                        JdbcSupport.str(rs, "model"),
                        JdbcSupport.str(rs, "provider"),
                        JdbcSupport.lng(rs, "calls"),
                        JdbcSupport.lng(rs, "cost"),
                        (long) JdbcSupport.dec(rs, "avg_latency").doubleValue()),
                since, limit);
    }

    public List<ProviderAgg> byProvider(LocalDateTime since) {
        return JdbcSupport.list(jdbc,
                "SELECT provider, COUNT(*) AS calls, COALESCE(SUM(cost_cents), 0) AS cost FROM llm_call "
                        + "WHERE created_at >= ? GROUP BY provider ORDER BY cost DESC",
                (rs, rowNum) -> new ProviderAgg(
                        JdbcSupport.str(rs, "provider"),
                        JdbcSupport.lng(rs, "calls"),
                        JdbcSupport.lng(rs, "cost")),
                since);
    }

    public List<DailyAgg> daily(LocalDateTime since) {
        return JdbcSupport.list(jdbc,
                "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS d, COUNT(*) AS calls, "
                        + "COALESCE(SUM(cost_cents), 0) AS cost FROM llm_call WHERE created_at >= ? "
                        + "GROUP BY DATE_FORMAT(created_at, '%Y-%m-%d') ORDER BY d",
                (rs, rowNum) -> new DailyAgg(
                        JdbcSupport.str(rs, "d"),
                        JdbcSupport.lng(rs, "calls"),
                        JdbcSupport.lng(rs, "cost")),
                since);
    }

    public List<String> distinctModels() {
        return jdbc.queryForList(
                "SELECT DISTINCT model FROM llm_call WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)",
                String.class);
    }
}
