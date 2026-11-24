package com.xingtu.agent.llm;

// ═══════ 文件级能力标注 ═══════
// [CAP-02] 模型接入与输出控制  |  [CAP-18] 成本与模型工程
// 职责：成本计算：价格表单位为「分 / 百万 token」，按调用向上取整（避免小额调用被记为 0）
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import org.springframework.stereotype.Component;

/**
 * 成本计算：价格表单位为「分 / 百万 token」，按调用向上取整（避免小额调用被记为 0）。
 *
 * <p>costCents = ceil((promptTokens * inputPrice + completionTokens * outputPrice) / 1_000_000)</p>
 */
@Component
public class CostCalculator {

    private final AppProperties props;

    public CostCalculator(AppProperties props) {
        this.props = props;
    }

    public int costCents(String model, int promptTokens, int completionTokens) {
        if (promptTokens <= 0 && completionTokens <= 0) {
            return 0;
        }
        AppProperties.Price price = priceOf(model);
        double cents = (promptTokens * (double) price.getInputPerMillionCents()
                + completionTokens * (double) price.getOutputPerMillionCents()) / 1_000_000d;
        if (cents <= 0d) {
            return 0;
        }
        return (int) Math.ceil(cents);
    }

    public int inputPrice(String model) {
        return priceOf(model).getInputPerMillionCents();
    }

    public int outputPrice(String model) {
        return priceOf(model).getOutputPerMillionCents();
    }

    /** 返回命中的价格（未配置的模型回退到全局默认价）。 */
    public AppProperties.Price priceOf(String model) {
        if (model != null) {
            AppProperties.Price configured = props.getPricing().getModels().get(model);
            if (configured != null) {
                return configured;
            }
        }
        AppProperties.Price fallback = new AppProperties.Price();
        fallback.setInputPerMillionCents(props.getPricing().getDefaultInputPerMillionCents());
        fallback.setOutputPerMillionCents(props.getPricing().getDefaultOutputPerMillionCents());
        return fallback;
    }
}
