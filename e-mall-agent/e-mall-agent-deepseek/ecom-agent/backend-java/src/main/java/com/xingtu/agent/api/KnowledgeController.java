package com.xingtu.agent.api;

// ═══════ 文件级能力标注 ═══════
// [CAP-01] 交互协议
// 职责：知识库接口（docs/03-API契约
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.api.dto.KnowledgeDtos;
import com.xingtu.agent.common.ApiResponse;
import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.RabbitPublisher;
import com.xingtu.agent.infra.repo.JobRepository;
import com.xingtu.agent.infra.repo.KnowledgeRepository;
import com.xingtu.agent.rag.HybridRetriever;
import com.xingtu.agent.rag.IngestService;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.Executor;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * 知识库接口（docs/03-API契约.md 第 5 节），RBAC 由 RbacInterceptor 统一拦截（ADMIN / OPS）。
 *
 * <p>上传后立即返回 {documentId, jobId, status=QUEUED}，真正索引走 RabbitMQ knowledge.index；
 * MQ 关闭时（本地 Mock 模式）退化为进程内异步索引，保证离线可跑通。</p>
 */
@RestController
@RequestMapping("/api/v1/knowledge")
public class KnowledgeController {

    private static final Logger log = LoggerFactory.getLogger(KnowledgeController.class);
    private static final Set<String> DOC_TYPES = Set.of("POLICY", "MANUAL", "FAQ", "PRODUCT_DOC");
    private static final Set<String> VISIBILITIES = Set.of("PUBLIC", "INTERNAL", "ADMIN");
    private static final int MAX_TOP_K = 20;

    private final KnowledgeRepository knowledgeRepository;
    private final JobRepository jobRepository;
    private final IngestService ingestService;
    private final HybridRetriever hybridRetriever;
    private final RabbitPublisher rabbitPublisher;
    private final AppProperties props;
    private final Executor agentExecutor;

    public KnowledgeController(KnowledgeRepository knowledgeRepository, JobRepository jobRepository,
                               IngestService ingestService, HybridRetriever hybridRetriever,
                               RabbitPublisher rabbitPublisher, AppProperties props,
                               @Qualifier("agentExecutor") Executor agentExecutor) {
        this.knowledgeRepository = knowledgeRepository;
        this.jobRepository = jobRepository;
        this.ingestService = ingestService;
        this.hybridRetriever = hybridRetriever;
        this.rabbitPublisher = rabbitPublisher;
        this.props = props;
        this.agentExecutor = agentExecutor;
    }

    @PostMapping(value = "/documents", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ApiResponse<KnowledgeDtos.DocumentUploadVO> upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "title", required = false) String title,
            @RequestParam(value = "docType", required = false) String docType,
            @RequestParam(value = "visibility", required = false) String visibility) {
        if (file == null || file.isEmpty()) {
            throw BizException.validation("file 不能为空");
        }
        String filename = file.getOriginalFilename() == null ? "未命名文档" : file.getOriginalFilename();
        String text = extractText(file);
        if (text.isBlank()) {
            throw BizException.validation("文件内容为空: " + filename);
        }
        String finalTitle = title == null || title.isBlank() ? stripExtension(filename) : title.trim();
        String finalDocType = normalizeDocType(docType);
        String finalVisibility = normalizeVisibility(visibility);

        long documentId = knowledgeRepository.insertDocument(finalTitle, finalDocType, filename,
                finalVisibility, "PENDING", checksum(text));
        ingestService.saveRawText(documentId, text);
        long jobId = jobRepository.insert(documentId, "INDEX", "QUEUED");
        if (props.getMq().isEnabled()) {
            rabbitPublisher.publishKnowledgeIndex(documentId, jobId);
        } else {
            agentExecutor.execute(() -> indexNow(documentId, jobId));
        }
        return ApiResponse.ok(new KnowledgeDtos.DocumentUploadVO(documentId, jobId, "QUEUED"));
    }

    @GetMapping("/documents")
    public ApiResponse<List<KnowledgeDtos.KnowledgeDocumentVO>> documents(
            @RequestParam(value = "docType", required = false) String docType,
            @RequestParam(value = "status", required = false) String status) {
        List<KnowledgeDtos.KnowledgeDocumentVO> items = new ArrayList<>();
        for (KnowledgeRepository.DocumentRow row : knowledgeRepository.listDocuments(docType, status, 100)) {
            items.add(new KnowledgeDtos.KnowledgeDocumentVO(row.id(), row.title(), row.docType(),
                    row.visibility(), row.status(), row.version(), row.chunkCount(),
                    JsonUtil.formatTime(row.createdAt())));
        }
        return ApiResponse.ok(items);
    }

    @DeleteMapping("/documents/{id}")
    public ApiResponse<KnowledgeDtos.JobIdVO> delete(@PathVariable("id") long documentId) {
        KnowledgeRepository.DocumentRow document = knowledgeRepository.findDocument(documentId);
        if (document == null || document.deletedAt() != null) {
            throw BizException.notFound("文档不存在: " + documentId);
        }
        long jobId = jobRepository.insert(documentId, "DELETE", "QUEUED");
        knowledgeRepository.softDelete(documentId);
        if (props.getMq().isEnabled()) {
            rabbitPublisher.publishKnowledgeDelete(documentId, jobId);
        } else {
            agentExecutor.execute(() -> deleteNow(documentId, jobId));
        }
        return ApiResponse.ok(new KnowledgeDtos.JobIdVO(jobId));
    }

    @PostMapping("/documents/{id}/reindex")
    public ApiResponse<KnowledgeDtos.JobIdVO> reindex(@PathVariable("id") long documentId) {
        KnowledgeRepository.DocumentRow document = knowledgeRepository.findDocument(documentId);
        if (document == null || document.deletedAt() != null) {
            throw BizException.notFound("文档不存在: " + documentId);
        }
        long jobId = jobRepository.insert(documentId, "REINDEX", "QUEUED");
        knowledgeRepository.updateStatus(documentId, "PENDING");
        if (props.getMq().isEnabled()) {
            rabbitPublisher.publishKnowledgeIndex(documentId, jobId);
        } else {
            agentExecutor.execute(() -> indexNow(documentId, jobId));
        }
        return ApiResponse.ok(new KnowledgeDtos.JobIdVO(jobId));
    }

    @GetMapping("/jobs/{jobId}")
    public ApiResponse<KnowledgeDtos.JobVO> job(@PathVariable("jobId") long jobId) {
        JobRepository.JobRow row = jobRepository.findById(jobId);
        if (row == null) {
            throw BizException.notFound("作业不存在: " + jobId);
        }
        return ApiResponse.ok(new KnowledgeDtos.JobVO(row.id(), row.documentId(), row.jobType(),
                row.status(), row.progress(), row.error()));
    }

    /** 检索调试：返回命中项 + 稠密/稀疏/重排三路分数与路由。 */
    @PostMapping("/search")
    public ApiResponse<KnowledgeDtos.KnowledgeSearchVO> search(
            @RequestBody(required = false) KnowledgeDtos.KnowledgeSearchReq req) {
        if (req == null || req.query() == null || req.query().isBlank()) {
            throw BizException.validation("query 不能为空");
        }
        int topK = req.topK() == null ? 5 : Math.max(1, Math.min(req.topK(), MAX_TOP_K));
        HybridRetriever.Result result = hybridRetriever.retrieve(req.query().trim(), topK,
                req.docTypes(), req.mode());
        List<KnowledgeDtos.KnowledgeHitVO> items = new ArrayList<>();
        for (HybridRetriever.HitDetail hit : result.hits()) {
            items.add(new KnowledgeDtos.KnowledgeHitVO(hit.chunkId(), hit.documentId(), hit.title(),
                    hit.content(), hit.score(), hit.denseScore(), hit.sparseScore(), hit.rerankScore(),
                    hit.route()));
        }
        HybridRetriever.Debug debug = result.debug();
        return ApiResponse.ok(new KnowledgeDtos.KnowledgeSearchVO(items,
                new KnowledgeDtos.RetrievalDebugVO(debug.denseTopK(), debug.sparseTopK(),
                        debug.rerankTopN(), debug.latencyMs())));
    }

    private void indexNow(long documentId, long jobId) {
        try {
            jobRepository.update(jobId, "RUNNING", 10, null);
            IngestService.IndexResult result = ingestService.indexDocument(documentId);
            boolean ok = "SUCCESS".equals(result.status()) || "SKIPPED".equals(result.status());
            jobRepository.update(jobId, ok ? "SUCCESS" : "FAILED", ok ? 100 : 0, result.message());
        } catch (RuntimeException e) {
            log.error("同步索引失败 documentId={} jobId={}", documentId, jobId, e);
            jobRepository.update(jobId, "FAILED", 0, e.getMessage());
        }
    }

    private void deleteNow(long documentId, long jobId) {
        try {
            jobRepository.update(jobId, "RUNNING", 10, null);
            ingestService.deleteVectors(documentId);
            knowledgeRepository.deleteChunks(documentId);
            jobRepository.update(jobId, "SUCCESS", 100, null);
        } catch (RuntimeException e) {
            log.error("清理向量失败 documentId={} jobId={}", documentId, jobId, e);
            jobRepository.update(jobId, "FAILED", 0, e.getMessage());
        }
    }

    private String normalizeDocType(String docType) {
        if (docType == null || docType.isBlank()) {
            return "FAQ";
        }
        String value = docType.trim().toUpperCase(Locale.ROOT);
        if (!DOC_TYPES.contains(value)) {
            throw BizException.validation("docType 只能是 " + DOC_TYPES);
        }
        return value;
    }

    private String normalizeVisibility(String visibility) {
        if (visibility == null || visibility.isBlank()) {
            return "PUBLIC";
        }
        String value = visibility.trim().toUpperCase(Locale.ROOT);
        if (!VISIBILITIES.contains(value)) {
            throw BizException.validation("visibility 只能是 " + VISIBILITIES);
        }
        return value;
    }

    /**
     * 文本抽取：.md/.txt 按 UTF-8 解码；.docx 走 ZIP + XML 去标签（仅 JDK 标准库）；
     * .pdf 用 PDFBox 抽取（与 Python 端 pypdf 对应，保证两端上传能力一致）。
     */
    private String extractText(MultipartFile file) {
        String filename = file.getOriginalFilename() == null ? "" : file.getOriginalFilename();
        String lower = filename.toLowerCase(Locale.ROOT);
        try {
            if (lower.endsWith(".md") || lower.endsWith(".txt")) {
                return new String(file.getBytes(), StandardCharsets.UTF_8);
            }
            if (lower.endsWith(".docx")) {
                return extractDocx(file.getInputStream());
            }
            if (lower.endsWith(".pdf")) {
                return extractPdf(file.getBytes());
            }
        } catch (IOException e) {
            throw new IllegalStateException("读取上传文件失败: " + e.getMessage(), e);
        }
        throw BizException.validation("暂不支持的文件类型（支持 .md / .txt / .docx / .pdf）: " + filename);
    }

    /** 用 PDFBox 抽取正文；加密或损坏的 PDF 统一转成可读的业务错误。 */
    private String extractPdf(byte[] bytes) {
        try (PDDocument document = PDDocument.load(new ByteArrayInputStream(bytes))) {
            if (document.isEncrypted()) {
                throw BizException.validation("PDF 已加密，无法解析，请先解密后再上传");
            }
            PDFTextStripper stripper = new PDFTextStripper();
            String text = stripper.getText(document);
            return text == null ? "" : text.trim();
        } catch (BizException e) {
            throw e;
        } catch (IOException e) {
            throw BizException.validation("PDF 解析失败: " + e.getMessage());
        }
    }

    private String extractDocx(InputStream input) throws IOException {
        try (ZipInputStream zip = new ZipInputStream(input)) {
            ZipEntry entry;
            while ((entry = zip.getNextEntry()) != null) {
                if (!"word/document.xml".equals(entry.getName())) {
                    continue;
                }
                ByteArrayOutputStream buffer = new ByteArrayOutputStream();
                byte[] chunk = new byte[8192];
                int read;
                while ((read = zip.read(chunk)) > 0) {
                    buffer.write(chunk, 0, read);
                }
                return xmlToText(buffer.toString(StandardCharsets.UTF_8));
            }
        }
        return "";
    }

    private String xmlToText(String xml) {
        String text = xml.replaceAll("(?i)</w:p>", "\n");
        text = text.replaceAll("(?i)<w:tab[^>]*/>", "\t");
        text = text.replaceAll("<[^>]+>", "");
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"")
                .replace("&#39;", "'").replace("&amp;", "&");
        text = text.replaceAll("[ \\t]+", " ");
        text = text.replaceAll("\\n{3,}", "\n\n");
        return text.trim();
    }

    private String checksum(String text) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256")
                    .digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(digest.length * 2);
            for (byte value : digest) {
                sb.append(Integer.toHexString((value & 0xFF) | 0x100).substring(1));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }

    private String stripExtension(String filename) {
        int dot = filename.lastIndexOf('.');
        String base = dot > 0 ? filename.substring(0, dot) : filename;
        return base.isBlank() ? "未命名文档" : base;
    }
}
