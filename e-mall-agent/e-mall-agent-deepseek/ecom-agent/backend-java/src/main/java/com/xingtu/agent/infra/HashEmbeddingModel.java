package com.xingtu.agent.infra;

// ═══════ 文件级能力标注 ═══════
// [CAP-14] 可靠性/降级
// 职责：确定性哈希向量：EMBEDDING_PROVIDER=hash 时使用，无需任何 API Key 即可离线跑通 RAG
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.rag.EmbeddingModel;
import org.springframework.stereotype.Component;

/**
 * 确定性哈希向量：EMBEDDING_PROVIDER=hash 时使用，无需任何 API Key 即可离线跑通 RAG。
 *
 * <p>算法：对 CJK 二元组 + 英文单词做 FNV-1a 64 位哈希，映射到 [0, dim) 的桶，
 * 按哈希奇偶决定符号，最后 L2 归一化。相同文本永远得到相同向量，
 * 语义相近的文本（共享 token）余弦相似度更高。</p>
 */
@Component
public class HashEmbeddingModel implements EmbeddingModel {

    private final int dim;

    public HashEmbeddingModel(AppProperties props) {
        this.dim = Math.max(32, props.getEmbedding().getDim());
    }

    @Override
    public int dim() {
        return dim;
    }

    @Override
    public String provider() {
        return "hash";
    }

    @Override
    public float[] embed(String text) {
        float[] vector = new float[dim];
        if (text == null || text.isBlank()) {
            return vector;
        }
        for (String token : tokenize(text)) {
            long hash = fnv1a(token);
            int index = (int) Math.floorMod(hash, (long) dim);
            float sign = ((hash >>> 33) & 1L) == 0L ? 1f : -1f;
            vector[index] += sign;
        }
        normalize(vector);
        return vector;
    }

    static void normalize(float[] vector) {
        double sum = 0d;
        for (float value : vector) {
            sum += (double) value * value;
        }
        double norm = Math.sqrt(sum);
        if (norm == 0d) {
            return;
        }
        for (int i = 0; i < vector.length; i++) {
            vector[i] = (float) (vector[i] / norm);
        }
    }

    /** 与 SparseEncoder 保持同一分词口径：CJK 二元组 + 小写英文/数字词。 */
    static java.util.List<String> tokenize(String text) {
        java.util.List<String> tokens = new java.util.ArrayList<>();
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

    static boolean isCjk(char c) {
        return (c >= 0x4E00 && c <= 0x9FFF) || (c >= 0x3400 && c <= 0x4DBF);
    }

    private long fnv1a(String token) {
        long hash = 0xcbf29ce484222325L;
        for (int i = 0; i < token.length(); i++) {
            hash ^= token.charAt(i);
            hash *= 0x100000001b3L;
        }
        return hash;
    }
}
