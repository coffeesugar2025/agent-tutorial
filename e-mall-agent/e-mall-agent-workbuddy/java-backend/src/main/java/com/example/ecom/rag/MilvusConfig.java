package com.example.ecom.rag;

import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.model.embedding.EmbeddingModel;
import dev.langchain4j.model.openai.OpenAiEmbeddingModel;
import dev.langchain4j.store.embedding.EmbeddingStore;
import dev.langchain4j.store.embedding.milvus.MilvusEmbeddingStore;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnExpression;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Duration;

/**
 * Milvus 条件装配：仅当 MILVUS_ENABLED=true 且配置了千问 Embedding Key 时生效。
 * 未满足时容器中不存在 EmbeddingStore/EmbeddingModel bean，RAG 自动回退关键词检索。
 * 版本核实：1.24.0 无 langchain4j-store-milvus，官方模块为 langchain4j-milvus（BOM 解析到 1.24.0-beta34）。
 */
@Configuration
public class MilvusConfig {

    @Bean
    @ConditionalOnExpression("'${app.rag.milvus-enabled:false}'.equals('true') && !'${app.llm.qwen.api-key:}'.isEmpty()")
    public EmbeddingModel embeddingModel(
            @Value("${app.llm.qwen.api-key:}") String apiKey,
            @Value("${app.llm.qwen.base-url:}") String baseUrl) {
        return OpenAiEmbeddingModel.builder()
                .apiKey(apiKey)
                .baseUrl(baseUrl)
                .modelName("text-embedding-v3")
                .timeout(Duration.ofSeconds(20))
                .build();
    }

    @Bean
    @ConditionalOnExpression("'${app.rag.milvus-enabled:false}'.equals('true') && !'${app.llm.qwen.api-key:}'.isEmpty()")
    public EmbeddingStore<TextSegment> embeddingStore(
            EmbeddingModel embeddingModel,
            @Value("${app.rag.milvus-host:localhost}") String host,
            @Value("${app.rag.milvus-port:19530}") int port,
            @Value("${app.rag.milvus-collection:ecom_docs}") String collection,
            @Value("${app.rag.milvus-token:}") String token,
            @Value("${app.rag.embedding-dim:1536}") int dimension) {
        return MilvusEmbeddingStore.builder()
                .host(host)
                .port(port)
                .collectionName(collection)
                .dimension(dimension)
                .token(token)
                .autoFlushOnInsert(true)
                .build();
    }
}
