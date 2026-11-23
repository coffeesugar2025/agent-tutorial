package com.xingtu.agent.rag;

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 检索离线评估：Recall@K / MRR / NDCG@K，用于回归检索质量（不依赖外部服务）。
 */
@Component
public class RetrievalEvaluator {

    public record GoldenCase(String caseId, String query, List<Long> relevantChunkIds) {
    }

    public record Metrics(double recallAtK, double mrr, double ndcgAtK, int caseCount, int k) {
    }

    public Metrics evaluate(List<GoldenCase> cases, List<List<Long>> retrieved, int k) {
        if (cases == null || cases.isEmpty()) {
            return new Metrics(0d, 0d, 0d, 0, k);
        }
        int limit = Math.max(1, k);
        double recallSum = 0d;
        double mrrSum = 0d;
        double ndcgSum = 0d;
        for (int i = 0; i < cases.size(); i++) {
            GoldenCase golden = cases.get(i);
            List<Long> hits = i < retrieved.size() && retrieved.get(i) != null ? retrieved.get(i) : List.of();
            Set<Long> relevant = new HashSet<>(golden.relevantChunkIds());
            if (relevant.isEmpty()) {
                continue;
            }
            recallSum += recall(relevant, hits, limit);
            mrrSum += reciprocalRank(relevant, hits, limit);
            ndcgSum += ndcg(relevant, hits, limit);
        }
        int count = cases.size();
        return new Metrics(round(recallSum / count), round(mrrSum / count), round(ndcgSum / count), count, k);
    }

    public double recall(Set<Long> relevant, List<Long> hits, int k) {
        int found = 0;
        for (int i = 0; i < Math.min(hits.size(), k); i++) {
            if (relevant.contains(hits.get(i))) {
                found++;
            }
        }
        return (double) found / relevant.size();
    }

    public double reciprocalRank(Set<Long> relevant, List<Long> hits, int k) {
        for (int i = 0; i < Math.min(hits.size(), k); i++) {
            if (relevant.contains(hits.get(i))) {
                return 1d / (i + 1d);
            }
        }
        return 0d;
    }

    public double ndcg(Set<Long> relevant, List<Long> hits, int k) {
        List<Long> top = new ArrayList<>();
        for (int i = 0; i < Math.min(hits.size(), k); i++) {
            top.add(hits.get(i));
        }
        double dcg = 0d;
        for (int i = 0; i < top.size(); i++) {
            int grade = relevant.contains(top.get(i)) ? 1 : 0;
            dcg += (Math.pow(2d, grade) - 1d) / log2(i + 2d);
        }
        double idcg = 0d;
        for (int i = 0; i < Math.min(relevant.size(), k); i++) {
            idcg += 1d / log2(i + 2d);
        }
        return idcg == 0d ? 0d : dcg / idcg;
    }

    private double log2(double value) {
        return Math.log(value) / Math.log(2d);
    }

    private double round(double value) {
        return Math.round(value * 10000d) / 10000d;
    }
}
