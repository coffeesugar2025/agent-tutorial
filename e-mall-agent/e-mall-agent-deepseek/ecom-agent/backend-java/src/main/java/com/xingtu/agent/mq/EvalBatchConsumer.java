package com.xingtu.agent.mq;

// ═══════ 文件级能力标注 ═══════
// [CAP-14] 可靠性/降级
// 职责：评测批次消费者：eval
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.RabbitConfig;
import com.xingtu.agent.eval.EvalRunner;
import com.xingtu.agent.infra.repo.AsyncTaskRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 评测批次消费者：eval.batch（契约第 8 节）。
 *
 * <p>POST /api/v1/admin/evals/run 只负责落 eval_run 并联调 MQ；真正的重复采样在消费者线程执行，
 * 避免 HTTP 请求被长任务阻塞。</p>
 */
@Component
@ConditionalOnProperty(prefix = "app.mq", name = "enabled", havingValue = "true", matchIfMissing = true)
public class EvalBatchConsumer {

    private static final Logger log = LoggerFactory.getLogger(EvalBatchConsumer.class);

    private final EvalRunner evalRunner;
    private final AsyncTaskRepository asyncTaskRepository;

    public EvalBatchConsumer(EvalRunner evalRunner, AsyncTaskRepository asyncTaskRepository) {
        this.evalRunner = evalRunner;
        this.asyncTaskRepository = asyncTaskRepository;
    }

    @RabbitListener(queues = RabbitConfig.QUEUE_EVAL_BATCH)
    public void onEvalBatch(Object payload) {
        Map<String, Object> data = MqSupport.toMap(payload);
        long runId = MqSupport.longValue(data, "runId");
        MqSupport.retry("EVAL_BATCH", data, asyncTaskRepository, log, () -> run(runId));
    }

    private void run(long runId) {
        if (runId <= 0) {
            throw new IllegalArgumentException("runId 缺失");
        }
        if (evalRunner.run(runId) == null) {
            throw new IllegalStateException("评测批次不存在 runId=" + runId);
        }
        log.info("评测批次执行完成 runId={}", runId);
    }
}
