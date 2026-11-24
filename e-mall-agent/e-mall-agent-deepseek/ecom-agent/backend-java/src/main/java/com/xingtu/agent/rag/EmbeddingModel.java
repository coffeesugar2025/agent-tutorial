package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：向量化抽象：dashscope / openai / ollama 走 HTTP，hash 走确定性本地实现
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

/**
 * 向量化抽象：dashscope / openai / ollama 走 HTTP，hash 走确定性本地实现。
 */
public interface EmbeddingModel {

    int dim();

    String provider();

    float[] embed(String text);
}
