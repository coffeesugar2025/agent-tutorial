package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：Embedding 工厂：按 EMBEDDING_PROVIDER 创建模型；远程模型失败时自动降级为 hash 向量，
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.EmbeddingFactory;
import com.xingtu.agent.infra.HashEmbeddingModel;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * Embedding 工厂：按 EMBEDDING_PROVIDER 创建模型；远程模型失败时自动降级为 hash 向量，
 * 保证检索链路不会因为外部依赖不可用而中断。
 */
@Component
public class EmbeddingModelFactory {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingModelFactory.class);

    private final EmbeddingModel primary;
    private final HashEmbeddingModel fallback;
    private volatile boolean degraded = false;

    public EmbeddingModelFactory(AppProperties props) {
        this.primary = EmbeddingFactory.create(props);
        this.fallback = new HashEmbeddingModel(props);
    }

    public EmbeddingModel model() {
        return primary;
    }

    public int dim() {
        return primary.dim();
    }

    public String provider() {
        return degraded ? fallback.provider() : primary.provider();
    }

    public boolean degraded() {
        return degraded;
    }

    public float[] embed(String text) {
        try {
            return primary.embed(text);
        } catch (RuntimeException e) {
            if (!degraded) {
                log.warn("Embedding 供应商 {} 不可用，降级为 hash 向量: {}", primary.provider(), e.getMessage());
                degraded = true;
            }
            return fallback.embed(text);
        }
    }

    public double cosine(float[] a, float[] b) {
        if (a == null || b == null || a.length != b.length || a.length == 0) {
            return 0d;
        }
        double dot = 0d;
        double normA = 0d;
        double normB = 0d;
        for (int i = 0; i < a.length; i++) {
            dot += a[i] * b[i];
            normA += a[i] * a[i];
            normB += b[i] * b[i];
        }
        if (normA == 0d || normB == 0d) {
            return 0d;
        }
        return dot / (Math.sqrt(normA) * Math.sqrt(normB));
    }
}
