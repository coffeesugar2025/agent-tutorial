package com.xingtu.agent.mq;

import com.xingtu.agent.config.RabbitConfig;
import com.xingtu.agent.infra.repo.AsyncTaskRepository;
import com.xingtu.agent.infra.repo.JobRepository;
import com.xingtu.agent.infra.repo.KnowledgeRepository;
import com.xingtu.agent.rag.IngestService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 知识库异步消费者：knowledge.index / knowledge.delete（契约第 8 节）。
 *
 * <p>索引重活（切片 + 向量化 + 写 Milvus）在消费者线程完成，HTTP 上传接口立即返回；
 * 失败重试 3 次后记 async_task DEAD，作业状态同步落 knowledge_job。</p>
 */
@Component
@ConditionalOnProperty(prefix = "app.mq", name = "enabled", havingValue = "true", matchIfMissing = true)
public class KnowledgeIndexConsumer {

    private static final Logger log = LoggerFactory.getLogger(KnowledgeIndexConsumer.class);

    private final KnowledgeRepository knowledgeRepository;
    private final JobRepository jobRepository;
    private final IngestService ingestService;
    private final AsyncTaskRepository asyncTaskRepository;

    public KnowledgeIndexConsumer(KnowledgeRepository knowledgeRepository, JobRepository jobRepository,
                                  IngestService ingestService, AsyncTaskRepository asyncTaskRepository) {
        this.knowledgeRepository = knowledgeRepository;
        this.jobRepository = jobRepository;
        this.ingestService = ingestService;
        this.asyncTaskRepository = asyncTaskRepository;
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_KNOWLEDGE_INDEX)
    public void onIndex(Object payload) {
        Map<String, Object> data = MqSupport.toMap(payload);
        long documentId = MqSupport.longValue(data, "documentId");
        long jobId = MqSupport.longValue(data, "jobId");
        MqSupport.retry("KNOWLEDGE_INDEX", data, asyncTaskRepository, log,
                () -> index(documentId, jobId));
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_KNOWLEDGE_DELETE)
    public void onDelete(Object payload) {
        Map<String, Object> data = MqSupport.toMap(payload);
        long documentId = MqSupport.longValue(data, "documentId");
        long jobId = MqSupport.longValue(data, "jobId");
        MqSupport.retry("KNOWLEDGE_DELETE", data, asyncTaskRepository, log,
                () -> delete(documentId, jobId));
    }

    private void index(long documentId, long jobId) {
        if (documentId <= 0) {
            throw new IllegalArgumentException("documentId 缺失");
        }
        if (jobId > 0) {
            jobRepository.update(jobId, "RUNNING", 10, null);
        }
        IngestService.IndexResult result = ingestService.indexDocument(documentId);
        boolean ok = "SUCCESS".equals(result.status()) || "SKIPPED".equals(result.status());
        if (jobId > 0) {
            jobRepository.update(jobId, ok ? "SUCCESS" : "FAILED", ok ? 100 : 0, result.message());
        }
        if (!ok) {
            throw new IllegalStateException("文档索引失败 documentId=" + documentId + ": "
                    + result.message());
        }
        log.info("文档索引完成 documentId={} status={} chunks={}", documentId, result.status(),
                result.chunkCount());
    }

    private void delete(long documentId, long jobId) {
        if (documentId <= 0) {
            throw new IllegalArgumentException("documentId 缺失");
        }
        if (jobId > 0) {
            jobRepository.update(jobId, "RUNNING", 10, null);
        }
        ingestService.deleteVectors(documentId);
        knowledgeRepository.deleteChunks(documentId);
        if (jobId > 0) {
            jobRepository.update(jobId, "SUCCESS", 100, null);
        }
        log.info("文档向量清理完成 documentId={}", documentId);
    }
}
