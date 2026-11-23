package com.example.ecom.security;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 输入注入扫描（规则版）：检测提示词注入 / 越权指令 / 破坏性 SQL 片段。
 * 结果包含 detected、score、matched 规则，供 /api/chat 与 frontier/security/scan 复用。
 */
@Component
public class InjectionScanner {

    public record ScanResult(boolean detected, double score, List<String> matched) {}

    private static final List<Rule> RULES = List.of(
            new Rule("ignore_previous", Pattern.compile("(?i)ignore\\s+(all\\s+)?previous\\s+instructions")),
            new Rule("disclose_prompt", Pattern.compile("(?i)(show|reveal|泄露|输出|打印).{0,8}(system\\s*prompt|提示词|系统指令)")),
            new Rule("jailbreak", Pattern.compile("(?i)(dan\\s+mode|developer\\s+mode|越狱|无视(所有)?规则)")),
            new Rule("role_override", Pattern.compile("(?i)(you\\s+are\\s+now|你现在是|假装你是).{0,20}(admin|管理员|root)")),
            new Rule("sql_destructive", Pattern.compile("(?i)\\b(drop\\s+table|delete\\s+from|truncate\\s+table)\\b")),
            new Rule("script_tag", Pattern.compile("(?i)<\\s*script[^>]*>")),
            new Rule("tool_abuse", Pattern.compile("(?i)(调用|执行|run)\\s+(所有|任意|any)\\s*(工具|tool)"))
    );

    private record Rule(String name, Pattern pattern) {}

    public ScanResult scan(String text) {
        if (text == null || text.isBlank()) return new ScanResult(false, 0.0, List.of());
        List<String> matched = new ArrayList<>();
        for (Rule rule : RULES) {
            if (rule.pattern().matcher(text).find()) matched.add(rule.name());
        }
        double score = Math.min(1.0, matched.size() * 0.34);
        return new ScanResult(!matched.isEmpty(), score, matched);
    }

    public boolean isSuspicious(String text) {
        return scan(text).detected();
    }
}
