package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：受限沙箱：OPS 的 run_python 只允许「聚合函数 + 数值列表」的确定性计算， 不启动解释器、不读文件、不联
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 受限沙箱：OPS 的 run_python 只允许「聚合函数 + 数值列表」的确定性计算，
 * 不启动解释器、不读文件、不联网（宁可少做也不做不安全的事）。
 *
 * <p>支持 sum/avg/mean/min/max/count/std，例如 {@code avg(120, 340, 560)}。</p>
 */
@Component
public class SandboxRunner {

    public record Result(boolean ok, String op, List<Double> values, double value, String message) {
    }

    private static final Pattern CALL = Pattern.compile(
            "(?i)^\\s*(sum|avg|mean|min|max|count|std)\\s*\\(([^()]*)\\)\\s*$");
    private static final Pattern NUMBER = Pattern.compile("-?\\d+(?:\\.\\d+)?");

    private final AppProperties props;

    public SandboxRunner(AppProperties props) {
        this.props = props;
    }

    public Result evaluate(String script) {
        if (!props.getSandbox().isEnabled()) {
            return new Result(false, null, List.of(), 0d, "沙箱执行已通过 SANDBOX_ENABLED=false 关闭");
        }
        if (script == null || script.isBlank()) {
            return new Result(false, null, List.of(), 0d, "脚本为空");
        }
        String lower = script.toLowerCase(Locale.ROOT);
        for (String forbidden : List.of("import", "open", "__", "os.", "sys.", "subprocess", "socket",
                "requests", "eval(", "exec(", "shutil", "pathlib")) {
            if (lower.contains(forbidden)) {
                return new Result(false, null, List.of(), 0d, "脚本包含禁止的片段: " + forbidden);
            }
        }
        Matcher matcher = CALL.matcher(script);
        if (!matcher.find()) {
            return new Result(false, null, List.of(), 0d,
                    "只支持聚合表达式，例如 avg(120,340,560)");
        }
        String op = matcher.group(1).toLowerCase(Locale.ROOT);
        List<Double> values = parseNumbers(matcher.group(2));
        if (values.isEmpty()) {
            return new Result(false, op, List.of(), 0d, "没有解析到数值");
        }
        double computed = compute(op, values);
        return new Result(true, op, values, computed,
                op + "(" + values.size() + " 个数) = " + trim(computed));
    }

    public double compute(String op, List<Double> values) {
        if (values == null || values.isEmpty()) {
            return 0d;
        }
        String normalized = op == null ? "sum" : op.toLowerCase(Locale.ROOT);
        double sum = 0d;
        double min = Double.MAX_VALUE;
        double max = -Double.MAX_VALUE;
        for (Double value : values) {
            sum += value;
            min = Math.min(min, value);
            max = Math.max(max, value);
        }
        switch (normalized) {
            case "avg":
            case "mean":
                return sum / values.size();
            case "min":
                return min;
            case "max":
                return max;
            case "count":
                return values.size();
            case "std":
                double mean = sum / values.size();
                double variance = 0d;
                for (Double value : values) {
                    variance += Math.pow(value - mean, 2);
                }
                return Math.sqrt(variance / values.size());
            case "sum":
            default:
                return sum;
        }
    }

    private List<Double> parseNumbers(String text) {
        List<Double> values = new ArrayList<>();
        Matcher matcher = NUMBER.matcher(text == null ? "" : text);
        while (matcher.find()) {
            try {
                values.add(Double.parseDouble(matcher.group()));
            } catch (NumberFormatException ignored) {
                // 非法数字直接跳过
            }
        }
        return values;
    }

    private String trim(double value) {
        if (Math.abs(value - Math.rint(value)) < 1e-9) {
            return String.valueOf((long) Math.rint(value));
        }
        return String.format(Locale.ROOT, "%.4f", value);
    }
}
