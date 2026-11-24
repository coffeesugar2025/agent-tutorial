package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：Text2SQL 守卫：只允许单条只读 SELECT，禁止注释、多语句、DDL/DML、文件读写与延时函数， 表名必须在
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.BizException;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Text2SQL 守卫：只允许单条只读 SELECT，禁止注释、多语句、DDL/DML、文件读写与延时函数，
 * 表名必须在白名单内，并强制加上 LIMIT。
 */
@Component
public class Text2SqlGuard {

    private static final List<String> ALLOWED_TABLES = List.of(
            "product", "category", "order_info", "order_item", "logistics", "refund_request",
            "chat_session", "chat_message", "approval_task", "agent_trace", "agent_span", "llm_call",
            "knowledge_document", "knowledge_chunk", "eval_run", "eval_case_result");

    /** 词边界匹配，避免 created_at 被 create 误杀。 */
    private static final List<Pattern> FORBIDDEN_PATTERNS = List.of(
            Pattern.compile("(?i)\\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|"
                    + "replace|merge|call|execute|exec|handler|load|rename|lock|unlock)\\b"),
            Pattern.compile("(?i)\\binto\\s+(outfile|dumpfile)\\b"),
            Pattern.compile("(?i)\\b(sleep|benchmark|load_file)\\s*\\("),
            Pattern.compile("(?i)\\b(information_schema|performance_schema|mysql|sys)\\."),
            Pattern.compile("@@"),
            Pattern.compile("(?i)\\b(union\\s+select)\\b"));

    private static final Pattern TABLE_PATTERN = Pattern.compile(
            "(?i)\\b(?:from|join)\\s+`?([a-zA-Z_][a-zA-Z0-9_]*)`?");
    private static final Pattern LIMIT_PATTERN = Pattern.compile("(?i)\\blimit\\s+\\d+");

    /** 校验并返回可直接执行的 SQL；不合法抛 40001。 */
    // ──────── [CAP-13] 结构化知识 ────────
    //   本处：Text2SQL 白名单 + 只读 + 强制 LIMIT
    //   域约束：只读 + 表白名单 + 强制 LIMIT，最后一层靠数据库只读账号兜底
    public String validate(String sql) {
        if (sql == null || sql.isBlank()) {
            throw BizException.validation("SQL 不能为空");
        }
        String normalized = sql.trim();
        while (normalized.endsWith(";")) {
            normalized = normalized.substring(0, normalized.length() - 1).trim();
        }
        String lower = normalized.toLowerCase(Locale.ROOT);
        if (!lower.startsWith("select ") && !lower.startsWith("with ")) {
            throw BizException.validation("只允许只读查询（SELECT / WITH）");
        }
        if (normalized.contains(";")) {
            throw BizException.validation("禁止多语句执行");
        }
        if (normalized.contains("--") || normalized.contains("/*") || normalized.contains("#")) {
            throw BizException.validation("禁止 SQL 注释");
        }
        for (Pattern pattern : FORBIDDEN_PATTERNS) {
            if (pattern.matcher(normalized).find()) {
                throw BizException.validation("SQL 中存在禁止的语法: " + pattern.pattern());
            }
        }
        List<String> tables = tables(normalized);
        if (tables.isEmpty()) {
            throw BizException.validation("SQL 必须包含 from 子句");
        }
        for (String table : tables) {
            if (!ALLOWED_TABLES.contains(table.toLowerCase(Locale.ROOT))) {
                throw BizException.validation("表 " + table + " 不在允许访问的范围内");
            }
        }
        return enforceLimit(normalized, 200);
    }

    public boolean isReadOnlySelect(String sql) {
        if (sql == null) {
            return false;
        }
        String normalized = sql.trim().toLowerCase(Locale.ROOT);
        return normalized.startsWith("select") && !normalized.contains(";");
    }

    public String enforceLimit(String sql, int max) {
        if (LIMIT_PATTERN.matcher(sql).find()) {
            return sql;
        }
        return sql + " LIMIT " + Math.max(1, max);
    }

    public List<String> tables(String sql) {
        List<String> tables = new ArrayList<>();
        Matcher matcher = TABLE_PATTERN.matcher(sql == null ? "" : sql);
        while (matcher.find()) {
            tables.add(matcher.group(1));
        }
        return tables;
    }

    public static List<String> allowedTables() {
        return ALLOWED_TABLES;
    }

    public static int forbiddenPatternCount() {
        return FORBIDDEN_PATTERNS.size();
    }
}
