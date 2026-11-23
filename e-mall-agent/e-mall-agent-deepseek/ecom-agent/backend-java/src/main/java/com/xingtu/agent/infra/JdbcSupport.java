package com.xingtu.agent.infra;

import com.xingtu.agent.common.JsonUtil;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;

import java.math.BigDecimal;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * JdbcTemplate 薄封装：只做四件事——插入返回自增主键、可空单行查询、动态参数、结果集取值。
 * 不使用任何 ORM，SQL 全部手写。
 */
public final class JdbcSupport {

    private JdbcSupport() {
    }

    /** 插入并返回自增主键。 */
    public static long insertAndReturnKey(JdbcTemplate jdbc, String sql, Object... args) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update(connection -> {
            PreparedStatement ps = connection.prepareStatement(sql, Statement.RETURN_GENERATED_KEYS);
            bind(ps, args);
            return ps;
        }, keyHolder);
        Number key = keyHolder.getKey();
        return key == null ? 0L : key.longValue();
    }

    /** 可空单行查询（无结果返回 null，不抛异常）。 */
    public static <T> T one(JdbcTemplate jdbc, String sql, RowMapper<T> mapper, Object... args) {
        List<T> rows = jdbc.query(sql, mapper, args);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public static <T> List<T> list(JdbcTemplate jdbc, String sql, RowMapper<T> mapper, Object... args) {
        return jdbc.query(sql, mapper, args);
    }

    public static int update(JdbcTemplate jdbc, String sql, Object... args) {
        return jdbc.update(sql, args);
    }

    public static long count(JdbcTemplate jdbc, String sql, Object... args) {
        Long value = jdbc.queryForObject(sql, Long.class, args);
        return value == null ? 0L : value;
    }

    public static void bind(PreparedStatement ps, Object[] args) throws SQLException {
        if (args == null) {
            return;
        }
        for (int i = 0; i < args.length; i++) {
            ps.setObject(i + 1, args[i]);
        }
    }

    public static String str(ResultSet rs, String column) {
        try {
            return rs.getString(column);
        } catch (SQLException e) {
            throw new IllegalStateException("读取列失败: " + column, e);
        }
    }

    public static long lng(ResultSet rs, String column) {
        try {
            return rs.getLong(column);
        } catch (SQLException e) {
            throw new IllegalStateException("读取列失败: " + column, e);
        }
    }

    public static int intVal(ResultSet rs, String column) {
        try {
            return rs.getInt(column);
        } catch (SQLException e) {
            throw new IllegalStateException("读取列失败: " + column, e);
        }
    }

    public static BigDecimal dec(ResultSet rs, String column) {
        try {
            return rs.getBigDecimal(column);
        } catch (SQLException e) {
            throw new IllegalStateException("读取列失败: " + column, e);
        }
    }

    public static LocalDateTime time(ResultSet rs, String column) {
        try {
            return rs.getObject(column, LocalDateTime.class);
        } catch (SQLException e) {
            throw new IllegalStateException("读取列失败: " + column, e);
        }
    }

    public static Map<String, Object> jsonMap(ResultSet rs, String column) {
        return JsonUtil.parseMap(str(rs, column));
    }

    /** 动态条件构造器：避免每个查询手写 StringBuilder + List 下标错误。 */
    public static final class Where {
        private final StringBuilder sql = new StringBuilder();
        private final List<Object> args = new ArrayList<>();

        public Where eq(String column, Object value) {
            if (value == null) {
                return this;
            }
            return condition(column + " = ?", value);
        }

        public Where gte(String column, Object value) {
            return value == null ? this : condition(column + " >= ?", value);
        }

        public Where lte(String column, Object value) {
            return value == null ? this : condition(column + " <= ?", value);
        }

        public Where like(String column, String value) {
            return value == null || value.isBlank() ? this : condition(column + " LIKE ?", "%" + value.trim() + "%");
        }

        public Where raw(String fragment, Object... values) {
            if (fragment == null || fragment.isBlank()) {
                return this;
            }
            sql.append(" AND ").append(fragment);
            for (Object value : values) {
                args.add(value);
            }
            return this;
        }

        private Where condition(String fragment, Object value) {
            sql.append(" AND ").append(fragment);
            args.add(value);
            return this;
        }

        public boolean isEmpty() {
            return sql.length() == 0;
        }

        public String clause() {
            return sql.toString();
        }

        public Object[] args() {
            return args.toArray();
        }

        public Object[] argsThen(Object... tail) {
            List<Object> all = new ArrayList<>(args);
            for (Object item : tail) {
                all.add(item);
            }
            return all.toArray();
        }
    }
}
