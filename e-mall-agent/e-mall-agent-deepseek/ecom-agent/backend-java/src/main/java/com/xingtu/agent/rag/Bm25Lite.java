package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：轻量 BM25（k1=1
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 轻量 BM25（k1=1.5, b=0.75）：不依赖全文索引，直接在候选切片上打分，
 * 因此 MySQL FULLTEXT 不可用时依然可以做稀疏检索。
 */
@Component
public class Bm25Lite {

    public record Doc(long id, String text) {
    }

    public record Scored(long id, double score) {
    }

    private static final double K1 = 1.5d;
    private static final double B = 0.75d;

    private final SparseEncoder encoder;

    public Bm25Lite(SparseEncoder encoder) {
        this.encoder = encoder;
    }

    public List<Scored> score(String query, List<Doc> docs, int topK) {
        List<Scored> results = new ArrayList<>();
        if (query == null || query.isBlank() || docs == null || docs.isEmpty()) {
            return results;
        }
        Map<String, Float> queryTerms = encoder.encode(query);
        List<Map<String, Float>> docTerms = new ArrayList<>(docs.size());
        double totalLength = 0d;
        Map<String, Integer> docFreq = new HashMap<>();
        for (Doc doc : docs) {
            Map<String, Float> terms = encoder.encode(doc.text());
            docTerms.add(terms);
            totalLength += length(terms);
            for (String term : terms.keySet()) {
                docFreq.merge(term, 1, Integer::sum);
            }
        }
        double avgLength = docs.isEmpty() ? 0d : totalLength / docs.size();
        if (avgLength <= 0d) {
            return results;
        }
        int docCount = docs.size();
        for (int i = 0; i < docs.size(); i++) {
            Map<String, Float> terms = docTerms.get(i);
            double docLength = length(terms);
            double score = 0d;
            for (String term : queryTerms.keySet()) {
                Float tf = terms.get(term);
                if (tf == null || tf <= 0f) {
                    continue;
                }
                int df = docFreq.getOrDefault(term, 0);
                double idf = Math.log(1d + (docCount - df + 0.5d) / (df + 0.5d));
                double numerator = tf * (K1 + 1d);
                double denominator = tf + K1 * (1d - B + B * docLength / avgLength);
                score += idf * numerator / denominator;
            }
            if (score > 0d) {
                results.add(new Scored(docs.get(i).id(), score));
            }
        }
        results.sort(Comparator.comparingDouble(Scored::score).reversed());
        if (results.size() > topK) {
            return new ArrayList<>(results.subList(0, topK));
        }
        return results;
    }

    private double length(Map<String, Float> terms) {
        double total = 0d;
        for (Float value : terms.values()) {
            total += value;
        }
        return total;
    }
}
