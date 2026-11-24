package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：Reciprocal Rank Fusion：RRF(d) = Σ 1 / (k + rank_i(d))，k 默认 6
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Reciprocal Rank Fusion：RRF(d) = Σ 1 / (k + rank_i(d))，k 默认 60。
 * 用于融合稠密与稀疏两路召回，避免两路分数量纲不一致。
 */
@Component
public class ReciprocalRankFusion {

    public static final int DEFAULT_K = 60;

    /** 返回按融合分数降序的 id 列表。 */
    public List<Long> fuse(List<List<Long>> rankings) {
        return fuse(rankings, DEFAULT_K);
    }

    public List<Long> fuse(List<List<Long>> rankings, int k) {
        List<Map.Entry<Long, Double>> entries = new ArrayList<>(scores(rankings, k).entrySet());
        entries.sort((a, b) -> Double.compare(b.getValue(), a.getValue()));
        List<Long> result = new ArrayList<>(entries.size());
        for (Map.Entry<Long, Double> entry : entries) {
            result.add(entry.getKey());
        }
        return result;
    }

    public Map<Long, Double> scores(List<List<Long>> rankings, int k) {
        Map<Long, Double> fused = new LinkedHashMap<>();
        if (rankings == null) {
            return fused;
        }
        for (List<Long> ranking : rankings) {
            if (ranking == null) {
                continue;
            }
            for (int position = 0; position < ranking.size(); position++) {
                Long id = ranking.get(position);
                if (id == null) {
                    continue;
                }
                double increment = 1d / (k + position + 1d);
                fused.merge(id, increment, Double::sum);
            }
        }
        return fused;
    }
}
