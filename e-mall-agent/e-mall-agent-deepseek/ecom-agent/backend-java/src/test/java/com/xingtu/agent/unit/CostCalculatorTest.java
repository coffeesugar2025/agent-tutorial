package com.xingtu.agent.unit;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：CostCalculatorTest
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.llm.CostCalculator;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class CostCalculatorTest {

    private AppProperties props;
    private CostCalculator calculator;

    @BeforeEach
    void setUp() {
        props = new AppProperties();
        props.getPricing().setDefaultInputPerMillionCents(200);
        props.getPricing().setDefaultOutputPerMillionCents(800);

        AppProperties.Price deepseek = new AppProperties.Price();
        deepseek.setInputPerMillionCents(100);
        deepseek.setOutputPerMillionCents(400);
        props.getPricing().getModels().put("deepseek-chat", deepseek);

        AppProperties.Price free = new AppProperties.Price();
        free.setInputPerMillionCents(0);
        free.setOutputPerMillionCents(0);
        props.getPricing().getModels().put("mock-chat", free);

        calculator = new CostCalculator(props);
    }

    @Test
    void usesConfiguredModelPrice() {
        assertEquals(100, calculator.costCents("deepseek-chat", 1_000_000, 0));
        assertEquals(400, calculator.costCents("deepseek-chat", 0, 1_000_000));
        assertEquals(300, calculator.costCents("deepseek-chat", 1_000_000, 500_000));
    }

    @Test
    void fallsBackToDefaultPriceForUnknownModel() {
        // (500000 * 200 + 250000 * 800) / 1_000_000 = 300
        assertEquals(300, calculator.costCents("unknown-model", 500_000, 250_000));
        assertEquals(200, calculator.inputPrice("unknown-model"));
        assertEquals(800, calculator.outputPrice("unknown-model"));
    }

    @Test
    void roundsUpTinyCallsToAvoidZeroCost() {
        assertEquals(1, calculator.costCents("deepseek-chat", 1, 0));
        assertEquals(1, calculator.costCents("deepseek-chat", 0, 1));
    }

    @Test
    void zeroTokensCostNothing() {
        assertEquals(0, calculator.costCents("deepseek-chat", 0, 0));
        assertEquals(0, calculator.costCents("mock-chat", 10_000, 10_000));
    }
}
