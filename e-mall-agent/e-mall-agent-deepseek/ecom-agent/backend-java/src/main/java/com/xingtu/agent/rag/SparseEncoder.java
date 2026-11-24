package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：稀疏编码：CJK 单字 + 二元组 + 小写英文/数字词，输出词频
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 稀疏编码：CJK 单字 + 二元组 + 小写英文/数字词，输出词频。
 * 与 HashEmbeddingModel 使用同一分词口径，保证稠密/稀疏检索可比。
 */
@Component
public class SparseEncoder {

    public Map<String, Float> encode(String text) {
        Map<String, Float> tf = new LinkedHashMap<>();
        for (String token : tokenize(text)) {
            tf.merge(token, 1f, Float::sum);
        }
        return tf;
    }

    public List<String> terms(String text) {
        return tokenize(text);
    }

    /** 关键词列表（去重，用于 MySQL LIKE 兜底召回）。 */
    public List<String> keywords(String text, int limit) {
        List<String> result = new ArrayList<>();
        for (String token : tokenize(text)) {
            if (token.length() >= 2 && !result.contains(token)) {
                result.add(token);
                if (result.size() >= limit) {
                    break;
                }
            }
        }
        return result;
    }

    public static List<String> tokenize(String text) {
        List<String> tokens = new ArrayList<>();
        if (text == null || text.isBlank()) {
            return tokens;
        }
        String lower = text.toLowerCase();
        StringBuilder latin = new StringBuilder();
        char previousCjk = 0;
        for (int i = 0; i < lower.length(); i++) {
            char c = lower.charAt(i);
            if (Character.isLetterOrDigit(c) && c < 0x2E80) {
                latin.append(c);
                previousCjk = 0;
                continue;
            }
            if (latin.length() > 0) {
                tokens.add(latin.toString());
                latin.setLength(0);
            }
            if (isCjk(c)) {
                if (previousCjk != 0) {
                    tokens.add(new String(new char[]{previousCjk, c}));
                }
                tokens.add(String.valueOf(c));
                previousCjk = c;
            } else {
                previousCjk = 0;
            }
        }
        if (latin.length() > 0) {
            tokens.add(latin.toString());
        }
        return tokens;
    }

    private static boolean isCjk(char c) {
        return (c >= 0x4E00 && c <= 0x9FFF) || (c >= 0x3400 && c <= 0x4DBF);
    }
}
