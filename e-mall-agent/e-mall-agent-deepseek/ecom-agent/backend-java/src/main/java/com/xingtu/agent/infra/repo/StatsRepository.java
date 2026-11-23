package com.xingtu.agent.infra.repo;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 运营大盘的按天聚合查询。
 *
 * <p>现有 Repository 只提供总量统计，overview 的 trend 需要「按天」维度，故单独拆一个
 * 只读聚合仓库，避免把 SQL 写进 AdminController。</p>
 */
@Repository
public class StatsRepository {

    public record DailyCount(String date, long count) {
    }

    private final JdbcTemplate jdbc;

    public StatsRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** 每天新建会话数（不含已删除会话）。 */
    public List<DailyCount> dailySessions(LocalDateTime since) {
        return jdbc.query(
                "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS d, COUNT(*) AS c FROM chat_session "
                        + "WHERE created_at >= ? AND status <> 'DELETED' GROUP BY d ORDER BY d",
                (rs, rowNum) -> new DailyCount(rs.getString("d"), rs.getLong("c")), since);
    }

    /** 每天消息数。 */
    public List<DailyCount> dailyMessages(LocalDateTime since) {
        return jdbc.query(
                "SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS d, COUNT(*) AS c FROM chat_message "
                        + "WHERE created_at >= ? GROUP BY d ORDER BY d",
                (rs, rowNum) -> new DailyCount(rs.getString("d"), rs.getLong("c")), since);
    }
}
