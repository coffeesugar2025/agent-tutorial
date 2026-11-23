package com.xingtu.agent.infra.repo;

import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * 用户表访问（sys_user）。
 */
@Repository
public class UserRepository {

    public record UserRow(long id, String username, String passwordHash, String displayName,
                          String email, List<String> roles, int status, LocalDateTime createdAt) {
    }

    private static final String COLUMNS =
            "id, username, password_hash, display_name, email, roles, status, created_at";

    private final JdbcTemplate jdbc;

    public UserRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public UserRow findByUsername(String username) {
        return JdbcSupport.one(jdbc, "SELECT " + COLUMNS + " FROM sys_user WHERE username = ?", mapper(), username);
    }

    public UserRow findById(long id) {
        return JdbcSupport.one(jdbc, "SELECT " + COLUMNS + " FROM sys_user WHERE id = ?", mapper(), id);
    }

    public long insert(String username, String passwordHash, String displayName, String email, String roles) {
        return JdbcSupport.insertAndReturnKey(jdbc,
                "INSERT INTO sys_user (username, password_hash, display_name, email, roles, status) "
                        + "VALUES (?, ?, ?, ?, ?, 1)",
                username, passwordHash, displayName, email, roles);
    }

    public List<String> parseRoles(String roles) {
        List<String> result = new ArrayList<>();
        if (roles == null || roles.isBlank()) {
            result.add("USER");
            return result;
        }
        for (String item : Arrays.asList(roles.split(","))) {
            String trimmed = item.trim();
            if (!trimmed.isEmpty()) {
                result.add(trimmed);
            }
        }
        if (result.isEmpty()) {
            result.add("USER");
        }
        return result;
    }

    private RowMapper<UserRow> mapper() {
        return (rs, rowNum) -> new UserRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "username"),
                JdbcSupport.str(rs, "password_hash"),
                JdbcSupport.str(rs, "display_name"),
                JdbcSupport.str(rs, "email"),
                parseRoles(JdbcSupport.str(rs, "roles")),
                JdbcSupport.intVal(rs, "status"),
                JdbcSupport.time(rs, "created_at"));
    }
}
