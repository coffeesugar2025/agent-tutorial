package com.xingtu.agent.unit;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：ChunkerTest
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.rag.Chunker;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ChunkerTest {

    @Test
    void blankTextProducesNoChunks() {
        Chunker chunker = new Chunker(120, 20);
        assertTrue(chunker.split(null).isEmpty());
        assertTrue(chunker.split("   ").isEmpty());
    }

    @Test
    void splitsBySentenceBoundaryWithSequentialIndexes() {
        Chunker chunker = new Chunker(120, 20);
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < 12; i++) {
            text.append("第").append(i).append("条退货政策说明需要逐字阅读。");
        }
        List<Chunker.Chunk> chunks = chunker.split(text.toString());
        assertTrue(chunks.size() >= 2, "长文本应被切成多块");
        for (int i = 0; i < chunks.size(); i++) {
            assertEquals(i, chunks.get(i).index());
            assertFalse(chunks.get(i).content().isBlank());
        }
    }

    @Test
    void hardSplitsOverlongSentenceWithoutPunctuation() {
        Chunker chunker = new Chunker(100, 0);
        String text = "a".repeat(250);
        List<Chunker.Chunk> chunks = chunker.split(text);
        assertEquals(3, chunks.size());
        int total = 0;
        for (Chunker.Chunk chunk : chunks) {
            assertTrue(chunk.content().length() <= 100);
            total += chunk.content().length();
        }
        assertEquals(250, total);
    }

    @Test
    void keepsParentContentAndTokenCount() {
        Chunker chunker = new Chunker(120, 8);
        String text = "星图商城支持 7 天无理由退货。运费由商家承担。";
        List<Chunker.Chunk> chunks = chunker.split(text);
        assertEquals(1, chunks.size());
        assertTrue(chunks.get(0).parentContent().contains("7 天无理由退货"));
        assertTrue(chunks.get(0).tokens() > 0);
    }

    @Test
    void overlapCarriesTailIntoNextChunk() {
        Chunker chunker = new Chunker(80, 20);
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < 10; i++) {
            text.append("第十二条关于退货运费承担规则的说明。");
        }
        List<Chunker.Chunk> chunks = chunker.split(text.toString());
        assertTrue(chunks.size() > 1);
        String first = chunks.get(0).content();
        String tail = first.substring(Math.max(0, first.length() - 10));
        assertTrue(chunks.get(1).content().contains(tail), "下一块应保留上一块的尾部重叠");
    }
}
