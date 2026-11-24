package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：检索引用（SSE citation 事件 / MessageVO
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

/**
 * 检索引用（SSE citation 事件 / MessageVO.citations / ContextAssembler 共用）。
 */
public record Citation(long docId, long chunkId, String title, String snippet, double score) {
}
