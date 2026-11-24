package com.xingtu.agent.unit;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：ReciprocalRankFusionTest
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.rag.ReciprocalRankFusion;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ReciprocalRankFusionTest {

    private final ReciprocalRankFusion rrf = new ReciprocalRankFusion();

    @Test
    void fusesTwoRankingsByReciprocalRank() {
        List<Long> fused = rrf.fuse(List.of(List.of(1L, 2L, 3L), List.of(3L, 1L)));
        assertEquals(List.of(1L, 3L, 2L), fused);
    }

    @Test
    void scoresSumAcrossRankings() {
        Map<Long, Double> scores = rrf.scores(List.of(List.of(1L, 2L), List.of(2L)), 60);
        double first = 1d / 61d;
        double second = 1d / 62d + 1d / 61d;
        assertEquals(first, scores.get(1L), 1e-9);
        assertEquals(second, scores.get(2L), 1e-9);
    }

    @Test
    void supportsCustomK() {
        assertEquals(List.of(5L, 6L), rrf.fuse(List.of(List.of(5L, 6L)), 0));
    }

    @Test
    void emptyAndNullInputsAreSafe() {
        assertTrue(rrf.fuse(List.of()).isEmpty());
        assertTrue(rrf.scores(null, 60).isEmpty());
        assertTrue(rrf.fuse(List.of(List.of(), List.of()), 60).isEmpty());
    }
}
