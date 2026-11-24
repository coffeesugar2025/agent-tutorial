package com.xingtu.agent.mq;

// ═══════ 文件级能力标注 ═══════
// [CAP-14] 可靠性/降级
// 职责：MQ 消费者公共工具：payload 归一化 + 3 次重试后落 async_task(status='DEAD')
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.infra.repo.AsyncTaskRepository;
import org.slf4j.Logger;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * MQ 消费者公共工具：payload 归一化 + 3 次重试后落 async_task(status='DEAD')。
 *
 * <p>与契约第 8 节一致：失败重试 3 次仍失败则记 DEAD，便于补偿任务/人工排查。
 * 消费者显式 ack（不抛出）避免消息在 x-dead-letter 与 async_task 之间重复记账。</p>
 */
public final class MqSupport {

    public static final int MAX_ATTEMPTS = 3;

    private MqSupport() {
    }

    /** 兼容 Jackson2JsonMessageConverter 的 LinkedHashMap 与字符串两种入参形态。 */
    public static Map<String, Object> toMap(Object payload) {
        if (payload instanceof Map<?, ?> map) {
            Map<String, Object> result = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                result.put(String.valueOf(entry.getKey()), entry.getValue());
            }
            return result;
        }
        if (payload instanceof String text) {
            return JsonUtil.parseMap(text);
        }
        return new LinkedHashMap<>();
    }

    public static long longValue(Map<String, Object> payload, String key) {
        Object value = payload.get(key);
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text) {
            try {
                return Long.parseLong(text.trim());
            } catch (NumberFormatException e) {
                return 0L;
            }
        }
        return 0L;
    }

    /** 执行 action，最多重试 MAX_ATTEMPTS 次；最终失败时写 DEAD 记录并吞掉异常（消息 ack）。 */
    public static void retry(String taskType, Map<String, Object> payload,
                             AsyncTaskRepository asyncTaskRepository, Logger log, Runnable action) {
        String error = null;
        for (int attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            try {
                action.run();
                return;
            } catch (RuntimeException e) {
                error = e.getMessage() == null ? e.toString() : e.getMessage();
                log.warn("MQ 任务 {} 第 {}/{} 次执行失败: {}", taskType, attempt, MAX_ATTEMPTS, error);
            }
        }
        recordDead(taskType, payload, asyncTaskRepository, log, error);
    }

    private static void recordDead(String taskType, Map<String, Object> payload,
                                   AsyncTaskRepository asyncTaskRepository, Logger log, String error) {
        try {
            long taskId = asyncTaskRepository.insert(taskType, JsonUtil.toJson(payload), MAX_ATTEMPTS);
            asyncTaskRepository.updateStatus(taskId, "DEAD", error);
            log.error("MQ 任务 {} 重试 {} 次仍失败，已记 async_task DEAD id={}",
                    taskType, MAX_ATTEMPTS, taskId);
        } catch (RuntimeException e) {
            log.error("MQ 任务 {} 落 async_task 失败: {}", taskType, e.getMessage());
        }
    }
}
