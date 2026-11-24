package com.xingtu.agent.rag;

// ═══════ 文件级能力标注 ═══════
// [CAP-12] 检索增强 RAG
// 职责：知识入库：原文暂存 -> 切片 -> 向量化 -> 写 MySQL + Milvus（失败落进程内）
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

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识入库：原文暂存 -> 切片 -> 向量化 -> 写 MySQL + Milvus（失败落进程内）。
 *
 * <p>原文不在 schema 中持久化，落盘到 {java.io.tmpdir}/ecom-agent-docs/{documentId}.txt，
 * 供异步消费者与 reindex 复用。</p>
 */
@Component
public class IngestService {

    private static final Logger log = LoggerFactory.getLogger(IngestService.class);

    public record IndexResult(String status, int chunkCount, String message) {
    }

    private final KnowledgeRepository knowledgeRepository;
    private final Chunker chunker;
    private final EmbeddingModelFactory embeddingFactory;
    private final MilvusVectorStore milvusVectorStore;
    private final InMemoryVectorStore inMemoryVectorStore;
    private final AppProperties props;
    private final Path storageDir;

    public IngestService(KnowledgeRepository knowledgeRepository, Chunker chunker,
                         EmbeddingModelFactory embeddingFactory, MilvusVectorStore milvusVectorStore,
                         InMemoryVectorStore inMemoryVectorStore, AppProperties props) {
        this.knowledgeRepository = knowledgeRepository;
        this.chunker = chunker;
        this.embeddingFactory = embeddingFactory;
        this.milvusVectorStore = milvusVectorStore;
        this.inMemoryVectorStore = inMemoryVectorStore;
        this.props = props;
        this.storageDir = Paths.get(System.getProperty("java.io.tmpdir"), "ecom-agent-docs");
    }

    /** 上传时暂存原文。 */
    public void saveRawText(long documentId, String text) {
        try {
            Files.createDirectories(storageDir);
            Files.writeString(fileOf(documentId), text == null ? "" : text, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("暂存文档原文失败: " + e.getMessage(), e);
        }
    }

    public String readRawText(long documentId) {
        Path file = fileOf(documentId);
        if (!Files.exists(file)) {
            return null;
        }
        try {
            return Files.readString(file, StandardCharsets.UTF_8);
        } catch (IOException e) {
            throw new IllegalStateException("读取文档原文失败: " + e.getMessage(), e);
        }
    }

    /** 异步索引入口（RabbitMQ consumer 调用，也支持幂等重放）。 */
    public IndexResult indexDocument(long documentId) {
        KnowledgeRepository.DocumentRow document = knowledgeRepository.findDocument(documentId);
        if (document == null || document.deletedAt() != null) {
            return new IndexResult("SKIPPED", 0, "文档不存在或已删除");
        }
        String text = readRawText(documentId);
        if (text == null || text.isBlank()) {
            knowledgeRepository.updateStatus(documentId, "FAILED");
            return new IndexResult("FAILED", 0, "缺少文档原文，请重新上传");
        }
        return indexText(documentId, text);
    }

    /** 直接按文本索引（上传后即时可用 / 测试友好）。 */
    public IndexResult indexText(long documentId, String text) {
        KnowledgeRepository.DocumentRow document = knowledgeRepository.findDocument(documentId);
        if (document == null) {
            return new IndexResult("SKIPPED", 0, "文档不存在");
        }
        knowledgeRepository.markIndexing(documentId);
        try {
            List<Chunker.Chunk> chunks = chunker.split(text);
            knowledgeRepository.deleteChunks(documentId);
            List<Long> chunkIds = new ArrayList<>();
            List<Map<String, Object>> milvusRows = new ArrayList<>();
            for (Chunker.Chunk chunk : chunks) {
                float[] vector = embeddingFactory.embed(chunk.content());
                Map<String, Object> metadata = new LinkedHashMap<>();
                metadata.put("chunkNo", chunk.index());
                metadata.put("vectorProvider", embeddingFactory.provider());
                metadata.put("embedding", toList(vector));
                long chunkId = knowledgeRepository.insertChunk(documentId, chunk.index(), chunk.content(),
                        chunk.parentContent(), chunk.tokens(), JsonUtil.toJson(metadata));
                chunkIds.add(chunkId);
                inMemoryVectorStore.put(VectorStore.Scope.KNOWLEDGE, chunkId, documentId, vector);
                milvusRows.add(milvusVectorStore.row(chunkId, documentId, vector));
            }
            writeVectors(milvusRows);
            knowledgeRepository.markReady(documentId, chunks.size());
            log.info("文档 {} 索引完成: origin={} chunks={} embed={}", documentId, document.title(),
                    chunks.size(), embeddingFactory.provider());
            return new IndexResult("SUCCESS", chunks.size(), null);
        } catch (RuntimeException e) {
            knowledgeRepository.updateStatus(documentId, "FAILED");
            log.error("文档 {} 索引失败: {}", documentId, e.getMessage());
            return new IndexResult("FAILED", 0, e.getMessage());
        }
    }

    /** 删除向量（软删除后的异步清理）。 */
    public void deleteVectors(long documentId) {
        try {
            milvusVectorStore.deleteByDocument(VectorStore.Scope.KNOWLEDGE, documentId);
        } catch (MilvusUnavailableException e) {
            log.debug("Milvus 删除失败，仅清理进程内向量: {}", e.getMessage());
        }
        inMemoryVectorStore.deleteByDocument(VectorStore.Scope.KNOWLEDGE, documentId);
    }

    private void writeVectors(List<Map<String, Object>> rows) {
        if (rows.isEmpty()) {
            return;
        }
        try {
            milvusVectorStore.putAll(VectorStore.Scope.KNOWLEDGE, rows);
        } catch (MilvusUnavailableException e) {
            log.warn("Milvus 写入失败，向量仅保留在进程内（重启后需 reindex）: {}", e.getMessage());
        }
    }

    private List<Double> toList(float[] vector) {
        List<Double> values = new ArrayList<>(vector.length);
        for (float value : vector) {
            values.add(Math.round(value * 1_000_000d) / 1_000_000d);
        }
        return values;
    }

    private Path fileOf(long documentId) {
        return storageDir.resolve(documentId + ".txt");
    }

    public int chunkSize() {
        return props.getRag().getChunkSize();
    }
}
