package com.example.ecom.rag;

import dev.langchain4j.data.embedding.Embedding;
import dev.langchain4j.data.segment.TextSegment;
import dev.langchain4j.model.embedding.EmbeddingModel;
import dev.langchain4j.model.output.Response;
import dev.langchain4j.store.embedding.EmbeddingMatch;
import dev.langchain4j.store.embedding.EmbeddingSearchRequest;
import dev.langchain4j.store.embedding.EmbeddingStore;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;

/** 检索服务：Milvus 向量检索（配置后）或关键词检索（默认回退），返回带来源的引用。 */
@Service
public class RetrievalService {

    private final DocumentIngestor ingestor;
    private final ObjectProvider<EmbeddingStore<TextSegment>> store;
    private final ObjectProvider<EmbeddingModel> model;
    private final int defaultTopK;

    public RetrievalService(DocumentIngestor ingestor,
                            ObjectProvider<EmbeddingStore<TextSegment>> store,
                            ObjectProvider<EmbeddingModel> model,
                            @Value("${app.rag.top-k:3}") int defaultTopK) {
        this.ingestor = ingestor;
        this.store = store;
        this.model = model;
        this.defaultTopK = defaultTopK;
    }

    public List<RagHit> retrieve(String query) {
        return retrieve(query, defaultTopK);
    }

    public List<RagHit> retrieve(String query, int topK) {
        if (query == null || query.isBlank()) return List.of();
        EmbeddingStore<TextSegment> vectorStore = store.getIfAvailable();
        EmbeddingModel embeddingModel = model.getIfAvailable();
        if (vectorStore != null && embeddingModel != null && ingestor.vectorIngest()) {
            try {
                Response<Embedding> embedded = embeddingModel.embed(query);
                var result = vectorStore.search(EmbeddingSearchRequest.builder()
                        .queryEmbedding(embedded.content())
                        .maxResults(topK)
                        .build());
                List<RagHit> hits = new ArrayList<>();
                for (EmbeddingMatch<TextSegment> match : result.matches()) {
                    TextSegment segment = match.embedded();
                    String source = "vector";
                    if (segment.metadata() != null && segment.metadata().getString("source") != null) {
                        source = segment.metadata().getString("source");
                    }
                    hits.add(new RagHit(segment.text(), match.score(), source));
                }
                return hits;
            } catch (RuntimeException ignored) {
                // 向量检索失败时回退关键词检索
            }
        }
        return keywordRetrieve(query, topK);
    }

    /** 简易 BM25 近似：查询词在文档中的覆盖率。 */
    public List<RagHit> keywordRetrieve(String query, int topK) {
        String q = query.toLowerCase(Locale.ROOT);
        String[] terms = q.split("\\s+");
        List<RagHit> hits = new ArrayList<>();
        for (DocumentIngestor.Chunk chunk : ingestor.chunks()) {
            String text = chunk.text().toLowerCase(Locale.ROOT);
            int matched = 0;
            for (String term : terms) {
                if (term.length() >= 2 && text.contains(term)) matched++;
            }
            if (matched > 0) {
                double score = Math.min(1.0, (double) matched / Math.max(1, terms.length));
                hits.add(new RagHit(chunk.text(), score, chunk.source()));
            }
        }
        hits.sort(Comparator.comparingDouble(RagHit::score).reversed());
        return hits.stream().limit(topK).toList();
    }
}
