package com.xingtu.agent.memory;

// ═══════ 文件级能力标注 ═══════
// [CAP-07] 记忆
// 职责：长期记忆（user_memory）：SEMANTIC / EPISODIC / PROCEDURAL 三类， 召回时用 
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.rag.EmbeddingModelFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 长期记忆（user_memory）：SEMANTIC / EPISODIC / PROCEDURAL 三类，
 * 召回时用 embedding 余弦相似度 + importance 加权。
 */
@Component
public class LongTermMemory {

    public record MemoryItem(long id, String type, String content, double importance, double score) {
    }

    private final JdbcTemplate jdbc;
    private final EmbeddingModelFactory embeddingFactory;

    public LongTermMemory(JdbcTemplate jdbc, EmbeddingModelFactory embeddingFactory) {
        this.jdbc = jdbc;
        this.embeddingFactory = embeddingFactory;
    }

    public long remember(long userId, String type, String content, double importance, Long sourceSession) {
        return com.xingtu.agent.infra.JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO user_memory (user_id, mem_type, content, importance, source_session, expires_at) "
                        + "VALUES (?, ?, ?, ?, ?, ?)",
                userId, type, content, BigDecimal.valueOf(clamp(importance)), sourceSession,
                LocalDateTime.now().plusDays(180));
    }

    public List<MemoryItem> recall(long userId, String query, int topK) {
        String sql = "SELECT id, mem_type, content, importance FROM user_memory WHERE user_id = ? "
                + "AND (expires_at IS NULL OR expires_at > NOW()) ORDER BY importance DESC LIMIT 200";
        List<MemoryItem> rows = jdbc.query(sql, (rs, rowNum) -> new MemoryItem(
                rs.getLong("id"),
                rs.getString("mem_type"),
                rs.getString("content"),
                rs.getBigDecimal("importance") == null ? 0.5d : rs.getBigDecimal("importance").doubleValue(),
                0d), userId);
        if (rows.isEmpty()) {
            return List.of();
        }
        if (query == null || query.isBlank()) {
            return rows.size() > topK ? new ArrayList<>(rows.subList(0, topK)) : rows;
        }
        float[] queryVector = embeddingFactory.embed(query);
        List<MemoryItem> scored = new ArrayList<>();
        for (MemoryItem row : rows) {
            double similarity = embeddingFactory.cosine(queryVector, embeddingFactory.embed(row.content()));
            scored.add(new MemoryItem(row.id(), row.type(), row.content(), row.importance(),
                    round(similarity * 0.7d + row.importance() * 0.3d)));
        }
        scored.sort(Comparator.comparingDouble(MemoryItem::score).reversed());
        return scored.size() > topK ? new ArrayList<>(scored.subList(0, topK)) : scored;
    }

    public void forget(long userId, long memoryId) {
        jdbc.update("DELETE FROM user_memory WHERE id = ? AND user_id = ?", memoryId, userId);
    }

    public String render(long userId, String query, int topK) {
        List<MemoryItem> items = recall(userId, query, topK);
        if (items.isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (MemoryItem item : items) {
            sb.append("- [").append(item.type()).append("] ").append(JsonUtil.toJson(item.content()))
                    .append('\n');
        }
        return sb.toString();
    }

    private double clamp(double importance) {
        return Math.max(0d, Math.min(1d, importance));
    }

    private double round(double value) {
        return Math.round(value * 10000d) / 10000d;
    }
}
