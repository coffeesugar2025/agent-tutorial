package com.xingtu.agent.eval;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * 评测判定器：关键词覆盖度打分，不调用外部模型，保证离线与 CI 可复现。
 *
 * <p>score = 必须命中词的覆盖率 −（出现禁止词 ? 0.5 : 0），四舍五入到 3 位小数；
 * 全部必中词命中、无禁止词且 score &gt;= {@link #PASS_THRESHOLD} 才算通过。</p>
 */
@Component
public class EvalJudge {

    public static final double PASS_THRESHOLD = 0.6d;

    public record Judgment(boolean passed, double score, String reason) {
    }

    public Judgment judge(EvalDataset.EvalCase testCase, String actual) {
        if (testCase == null) {
            return new Judgment(false, 0d, "用例为空");
        }
        String answer = actual == null ? "" : actual;
        if (answer.isBlank()) {
            return new Judgment(false, 0d, "回答为空");
        }
        String haystack = answer.toLowerCase(Locale.ROOT);
        List<String> required = testCase.mustContain() == null ? List.of() : testCase.mustContain();
        List<String> forbidden = testCase.mustNotContain() == null ? List.of() : testCase.mustNotContain();

        List<String> missing = new ArrayList<>();
        for (String keyword : required) {
            if (keyword == null || keyword.isBlank()) {
                continue;
            }
            if (!haystack.contains(keyword.toLowerCase(Locale.ROOT))) {
                missing.add(keyword);
            }
        }
        List<String> violated = new ArrayList<>();
        for (String keyword : forbidden) {
            if (keyword == null || keyword.isBlank()) {
                continue;
            }
            if (haystack.contains(keyword.toLowerCase(Locale.ROOT))) {
                violated.add(keyword);
            }
        }

        double coverage = required.isEmpty() ? 1d : (required.size() - missing.size()) / (double) required.size();
        double penalty = violated.isEmpty() ? 0d : 0.5d;
        double score = clamp(round3(coverage - penalty));
        boolean passed = missing.isEmpty() && violated.isEmpty() && score >= PASS_THRESHOLD;

        StringBuilder reason = new StringBuilder();
        if (missing.isEmpty()) {
            reason.append("关键词全部命中");
        } else {
            reason.append("缺少关键词: ").append(String.join("、", missing));
        }
        if (!violated.isEmpty()) {
            reason.append("；出现禁止词: ").append(String.join("、", violated));
        }
        return new Judgment(passed, score, reason.toString());
    }

    private double clamp(double value) {
        return Math.max(0d, Math.min(1d, value));
    }

    private double round3(double value) {
        return Math.round(value * 1000d) / 1000d;
    }
}
