package com.xingtu.agent.rag;

/**
 * 向量化抽象：dashscope / openai / ollama 走 HTTP，hash 走确定性本地实现。
 */
public interface EmbeddingModel {

    int dim();

    String provider();

    float[] embed(String text);
}
