package com.xingtu.agent.rag;

/**
 * 检索引用（SSE citation 事件 / MessageVO.citations / ContextAssembler 共用）。
 */
public record Citation(long docId, long chunkId, String title, String snippet, double score) {
}
