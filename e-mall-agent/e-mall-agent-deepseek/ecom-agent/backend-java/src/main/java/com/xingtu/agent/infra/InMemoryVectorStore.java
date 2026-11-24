package com.xingtu.agent.infra;

// ═══════ 文件级能力标注 ═══════
// [CAP-14] 可靠性/降级
// 职责：进程内向量库：Milvus 不可用时的降级路径，同时也用于单元测试
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 进程内向量库：Milvus 不可用时的降级路径，同时也用于单元测试。
 * 相似度为余弦相似度，向量在写入时已归一化。
 */
@Component
public class InMemoryVectorStore implements VectorStore {

    private record Entry(long id, long documentId, float[] vector) {
    }

    private final Map<String, Map<Long, Entry>> buckets = new ConcurrentHashMap<>();

    @Override
    public String backend() {
        return "in-memory";
    }

    @Override
    public boolean available() {
        return true;
    }

    @Override
    public void put(Scope scope, long id, long documentId, float[] vector) {
        if (vector == null || vector.length == 0) {
            return;
        }
        buckets.computeIfAbsent(scope.key(), key -> new ConcurrentHashMap<>())
                .put(id, new Entry(id, documentId, vector));
    }

    @Override
    public List<Hit> search(Scope scope, float[] vector, int topK, Long documentId) {
        List<Hit> hits = new ArrayList<>();
        if (vector == null || vector.length == 0) {
            return hits;
        }
        Map<Long, Entry> bucket = buckets.get(scope.key());
        if (bucket == null || bucket.isEmpty()) {
            return hits;
        }
        for (Entry entry : bucket.values()) {
            if (documentId != null && entry.documentId() != documentId) {
                continue;
            }
            if (entry.vector().length != vector.length) {
                continue;
            }
            hits.add(new Hit(entry.id(), entry.documentId(), cosine(vector, entry.vector())));
        }
        hits.sort(Comparator.comparingDouble(Hit::score).reversed());
        return hits.size() > topK ? new ArrayList<>(hits.subList(0, topK)) : hits;
    }

    @Override
    public void deleteByDocument(Scope scope, long documentId) {
        Map<Long, Entry> bucket = buckets.get(scope.key());
        if (bucket == null) {
            return;
        }
        bucket.entrySet().removeIf(entry -> entry.getValue().documentId() == documentId);
    }

    /** 清空（测试用）。 */
    public void clear() {
        buckets.clear();
    }

    public int size(Scope scope) {
        Map<Long, Entry> bucket = buckets.get(scope.key());
        return bucket == null ? 0 : bucket.size();
    }

    private double cosine(float[] a, float[] b) {
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
