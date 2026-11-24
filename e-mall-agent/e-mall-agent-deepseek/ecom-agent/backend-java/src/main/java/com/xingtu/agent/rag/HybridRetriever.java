package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：混合检索：稠密（Milvus → 进程内向量）+ 稀疏（BM25）→ RRF 融合 → 重排
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.InMemoryVectorStore;
import com.xingtu.agent.infra.MilvusUnavailableException;
import com.xingtu.agent.infra.VectorStore;
import com.xingtu.agent.infra.repo.KnowledgeRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 混合检索：稠密（Milvus → 进程内向量）+ 稀疏（BM25）→ RRF 融合 → 重排。
 * 三档降级：Milvus 不可用 → 进程内向量；进程内无向量 → 仅稀疏；重排失败 → 词面打分。
 */
@Component
public class HybridRetriever {

    private static final Logger log = LoggerFactory.getLogger(HybridRetriever.class);

    public record HitDetail(long chunkId, long documentId, String title, String content, double score,
                            double denseScore, double sparseScore, double rerankScore, String route) {
    }

    public record Debug(int denseTopK, int sparseTopK, int rerankTopN, long latencyMs, String denseRoute) {
    }

    public record Result(List<Citation> citations, List<HitDetail> hits, Debug debug) {
        public static Result empty(long latencyMs) {
            return new Result(List.of(), List.of(), new Debug(0, 0, 0, latencyMs, "none"));
        }
    }

    private final KnowledgeRepository knowledgeRepository;
    private final EmbeddingModelFactory embeddingFactory;
    private final MilvusVectorStore milvusVectorStore;
    private final InMemoryVectorStore inMemoryVectorStore;
    private final Bm25Lite bm25;
    private final ReciprocalRankFusion rrf;
    private final LlmReranker reranker;
    private final AppProperties props;

    public HybridRetriever(KnowledgeRepository knowledgeRepository, EmbeddingModelFactory embeddingFactory,
                           MilvusVectorStore milvusVectorStore, InMemoryVectorStore inMemoryVectorStore,
                           Bm25Lite bm25, ReciprocalRankFusion rrf, LlmReranker reranker,
                           AppProperties props) {
        this.knowledgeRepository = knowledgeRepository;
        this.embeddingFactory = embeddingFactory;
        this.milvusVectorStore = milvusVectorStore;
        this.inMemoryVectorStore = inMemoryVectorStore;
        this.bm25 = bm25;
        this.rrf = rrf;
        this.reranker = reranker;
        this.props = props;
    }

    public Result retrieve(String query) {
        return retrieve(query, props.getRag().getRerankTopN(), null, "hybrid");
    }

    // ──────── [CAP-12] 检索增强 RAG ────────
    //   本处：混合检索（dense + BM25 → RRF → 重排）
    //   域约束：任一环节失败必须降级并标记 degraded，不允许静默返回空结果
    public Result retrieve(String query, int topK, List<String> docTypes, String mode) {
        long start = System.currentTimeMillis();
        if (query == null || query.isBlank()) {
            return Result.empty(System.currentTimeMillis() - start);
        }
        Map<Long, KnowledgeRepository.DocumentRow> documents = loadDocuments(docTypes);
        List<KnowledgeRepository.ChunkRow> candidates = loadCandidates(documents);
        if (candidates.isEmpty()) {
            return Result.empty(System.currentTimeMillis() - start);
        }
        Map<Long, KnowledgeRepository.ChunkRow> chunkIndex = new HashMap<>();
        for (KnowledgeRepository.ChunkRow row : candidates) {
            chunkIndex.put(row.id(), row);
        }

        int denseTopK = Math.max(1, props.getRag().getDenseTopK());
        int sparseTopK = Math.max(1, props.getRag().getSparseTopK());
        int rerankTopN = Math.max(1, Math.min(topK <= 0 ? props.getRag().getRerankTopN() : topK, 20));
        String normalizedMode = mode == null || mode.isBlank() ? "hybrid" : mode.toLowerCase();

        Map<Long, Double> denseScores = new HashMap<>();
        List<Long> denseRanking = new ArrayList<>();
        String denseRoute = "none";
        if (!"sparse".equals(normalizedMode)) {
            denseRoute = dense(query, candidates, denseTopK, denseScores, denseRanking);
        }

        Map<Long, Double> sparseScores = new HashMap<>();
        List<Long> sparseRanking = new ArrayList<>();
        if (!"dense".equals(normalizedMode)) {
            List<Bm25Lite.Doc> docs = new ArrayList<>();
            for (KnowledgeRepository.ChunkRow row : candidates) {
                docs.add(new Bm25Lite.Doc(row.id(), row.content()));
            }
            for (Bm25Lite.Scored scored : bm25.score(query, docs, sparseTopK)) {
                sparseScores.put(scored.id(), scored.score());
                sparseRanking.add(scored.id());
            }
        }

        List<List<Long>> rankings = new ArrayList<>();
        rankings.add(denseRanking);
        rankings.add(sparseRanking);
        Map<Long, Double> fused = rrf.scores(rankings, ReciprocalRankFusion.DEFAULT_K);
        List<Long> fusedIds = rrf.fuse(rankings, ReciprocalRankFusion.DEFAULT_K);
        if (fusedIds.isEmpty()) {
            return Result.empty(System.currentTimeMillis() - start);
        }

        int candidateCount = Math.min(fusedIds.size(), rerankTopN * 3);
        List<LlmReranker.Candidate> rerankCandidates = new ArrayList<>();
        for (int i = 0; i < candidateCount; i++) {
            Long id = fusedIds.get(i);
            KnowledgeRepository.ChunkRow row = chunkIndex.get(id);
            if (row == null) {
                continue;
            }
            KnowledgeRepository.DocumentRow doc = documents.get(row.documentId());
            rerankCandidates.add(new LlmReranker.Candidate(row.id(), row.documentId(),
                    doc == null ? "知识文档" : doc.title(), row.content(), fused.getOrDefault(id, 0d)));
        }
        List<LlmReranker.Ranked> ranked = reranker.rerank(query, rerankCandidates, rerankTopN);

        List<HitDetail> hits = new ArrayList<>();
        List<Citation> citations = new ArrayList<>();
        for (LlmReranker.Ranked item : ranked) {
            double denseScore = round(denseScores.getOrDefault(item.chunkId(), 0d));
            double sparseScore = sparseScores.getOrDefault(item.chunkId(), 0d);
            if (item.rerankScore() < props.getRag().getMinScore()) {
                continue;
            }
            String route = routeOf(denseScore, sparseScore);
            String snippet = snippet(item.content());
            hits.add(new HitDetail(item.chunkId(), item.docId(), item.title(), item.content(),
                    round(item.rerankScore()), denseScore, round(sparseScore), item.rerankScore(), route));
            citations.add(new Citation(item.docId(), item.chunkId(), item.title(), snippet,
                    round(item.rerankScore())));
        }
        long latency = System.currentTimeMillis() - start;
        return new Result(citations, hits, new Debug(denseTopK, sparseTopK, rerankTopN, latency, denseRoute));
    }

    private String dense(String query, List<KnowledgeRepository.ChunkRow> candidates, int topK,
                         Map<Long, Double> denseScores, List<Long> ranking) {
        float[] vector = embeddingFactory.embed(query);
        Set<Long> candidateIds = new LinkedHashSet<>();
        for (KnowledgeRepository.ChunkRow row : candidates) {
            candidateIds.add(row.id());
        }
        try {
            List<VectorStore.Hit> hits = milvusVectorStore.search(VectorStore.Scope.KNOWLEDGE, vector, topK, null);
            for (VectorStore.Hit hit : hits) {
                if (candidateIds.contains(hit.id())) {
                    denseScores.put(hit.id(), hit.score());
                    ranking.add(hit.id());
                }
            }
            if (!ranking.isEmpty()) {
                return "milvus";
            }
        } catch (MilvusUnavailableException e) {
            log.debug("Milvus 检索不可用，降级为进程内向量: {}", e.getMessage());
        }
        return inMemoryDense(vector, candidates, topK, denseScores, ranking);
    }

    private String inMemoryDense(float[] vector, List<KnowledgeRepository.ChunkRow> candidates, int topK,
                                 Map<Long, Double> denseScores, List<Long> ranking) {
        for (KnowledgeRepository.ChunkRow row : candidates) {
            inMemoryVectorStore.put(VectorStore.Scope.KNOWLEDGE, row.id(), row.documentId(),
                    vectorOf(row));
        }
        for (VectorStore.Hit hit : inMemoryVectorStore.search(VectorStore.Scope.KNOWLEDGE, vector, topK, null)) {
            denseScores.put(hit.id(), hit.score());
            ranking.add(hit.id());
        }
        return "in-memory";
    }

    /** 优先复用索引时落库的向量，缺失时现算（并写回进程内缓存）。 */
    private float[] vectorOf(KnowledgeRepository.ChunkRow row) {
        Map<String, Object> metadata = JsonUtil.parseMap(row.metadata());
        Object raw = metadata.get("embedding");
        if (raw instanceof List<?> list && !list.isEmpty()) {
            float[] vector = new float[list.size()];
            for (int i = 0; i < list.size(); i++) {
                Object value = list.get(i);
                vector[i] = value instanceof Number number ? number.floatValue() : 0f;
            }
            return vector;
        }
        return embeddingFactory.embed(row.content());
    }

    private Map<Long, KnowledgeRepository.DocumentRow> loadDocuments(List<String> docTypes) {
        Map<Long, KnowledgeRepository.DocumentRow> documents = new LinkedHashMap<>();
        for (KnowledgeRepository.DocumentRow row : knowledgeRepository.listDocuments(null, "READY", 500)) {
            if ("ADMIN".equalsIgnoreCase(row.visibility())) {
                continue;
            }
            if (docTypes != null && !docTypes.isEmpty() && !docTypes.contains(row.docType())) {
                continue;
            }
            documents.put(row.id(), row);
        }
        return documents;
    }

    private List<KnowledgeRepository.ChunkRow> loadCandidates(
            Map<Long, KnowledgeRepository.DocumentRow> documents) {
        List<KnowledgeRepository.ChunkRow> result = new ArrayList<>();
        if (documents.isEmpty()) {
            return result;
        }
        for (KnowledgeRepository.ChunkRow row : knowledgeRepository.recentChunks(
                props.getRag().getCandidateLimit())) {
            if (documents.containsKey(row.documentId())) {
                result.add(row);
            }
        }
        return result;
    }

    private String routeOf(double denseScore, double sparseScore) {
        if (denseScore > 0d && sparseScore > 0d) {
            return "dense+sparse";
        }
        if (denseScore > 0d) {
            return "dense";
        }
        return "sparse";
    }

    private String snippet(String content) {
        if (content == null) {
            return "";
        }
        String single = content.replace('\n', ' ').trim();
        return single.length() <= 160 ? single : single.substring(0, 160) + "…";
    }

    private double round(double value) {
        return Math.round(value * 10000d) / 10000d;
    }
}
