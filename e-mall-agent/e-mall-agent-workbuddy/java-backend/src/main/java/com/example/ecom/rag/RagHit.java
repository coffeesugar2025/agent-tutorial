package com.example.ecom.rag;

/** 检索命中：文本、相似度、来源。 */
public record RagHit(String text, double score, String source) {
}
