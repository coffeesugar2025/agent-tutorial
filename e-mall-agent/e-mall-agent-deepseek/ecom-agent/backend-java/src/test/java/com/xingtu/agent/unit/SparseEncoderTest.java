package com.xingtu.agent.unit;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：SparseEncoderTest
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.rag.SparseEncoder;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SparseEncoderTest {

    private final SparseEncoder encoder = new SparseEncoder();

    @Test
    void tokenizesCjkAsUnigramsAndBigrams() {
        List<String> tokens = SparseEncoder.tokenize("拍照手机");
        assertTrue(tokens.contains("拍"));
        assertTrue(tokens.contains("拍照"));
        assertTrue(tokens.contains("手机"));
        assertEquals(7, tokens.size());
    }

    @Test
    void tokenizesLatinInLowerCase() {
        List<String> tokens = SparseEncoder.tokenize("iPhone 15 Pro");
        assertTrue(tokens.contains("iphone"));
        assertTrue(tokens.contains("15"));
        assertTrue(tokens.contains("pro"));
    }

    @Test
    void blankTextHasNoTokens() {
        assertTrue(SparseEncoder.tokenize(null).isEmpty());
        assertTrue(SparseEncoder.tokenize("  ").isEmpty());
    }

    @Test
    void keywordsDropSingleCharsAndDuplicates() {
        List<String> keywords = encoder.keywords("拍照 手机 拍照", 10);
        assertEquals(2, keywords.size());
        assertTrue(keywords.contains("拍照"));
        assertTrue(keywords.contains("手机"));
    }

    @Test
    void encodeCountsTermFrequency() {
        Map<String, Float> tf = encoder.encode("手机手机");
        assertEquals(2.0f, tf.get("手机").floatValue(), 1e-6f);
        assertFalse(tf.isEmpty());
    }
}
