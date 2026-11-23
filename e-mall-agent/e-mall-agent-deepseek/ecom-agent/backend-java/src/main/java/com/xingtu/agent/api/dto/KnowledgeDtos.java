package com.xingtu.agent.api.dto;

import java.util.List;

/**
 * 知识库相关 DTO（docs/03-API契约.md 第 5 节）。
 */
public final class KnowledgeDtos {

    private KnowledgeDtos() {
    }

    /** 上传响应 data：立即返回，索引为异步任务。 */
    public record DocumentUploadVO(long documentId, long jobId, String status) {
    }

    /** 文档视图。 */
    public record KnowledgeDocumentVO(long id, String title, String docType, String visibility,
                                      String status, int version, int chunkCount, String createdAt) {
    }

    /** DELETE / POST reindex 的 data：{"jobId":10}。 */
    public record JobIdVO(long jobId) {
    }

    /** 异步作业视图。 */
    public record JobVO(long id, long documentId, String jobType, String status, int progress,
                        String error) {
    }

    /** POST /api/v1/knowledge/search 请求体。 */
    public record KnowledgeSearchReq(String query, Integer topK, List<String> docTypes, String mode) {
    }

    /** 检索命中项。 */
    public record KnowledgeHitVO(long chunkId, long documentId, String title, String content,
                                 double score, double denseScore, double sparseScore,
                                 double rerankScore, String route) {
    }

    /** 检索调试信息。 */
    public record RetrievalDebugVO(int denseTopK, int sparseTopK, int rerankTopN, long latencyMs) {
    }

    /** 检索调试响应 data。 */
    public record KnowledgeSearchVO(List<KnowledgeHitVO> items, RetrievalDebugVO debug) {
    }
}
