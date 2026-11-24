package com.xingtu.agent.api.dto;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议  （支撑）
// 职责：知识库相关 DTO（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

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
