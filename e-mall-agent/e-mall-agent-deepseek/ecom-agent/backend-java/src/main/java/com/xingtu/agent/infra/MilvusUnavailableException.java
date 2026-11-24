package com.xingtu.agent.infra;

// ═══════ 文件级能力标注 ═══════
// [CAP-14] 可靠性/降级
// 职责：Milvus 不可用（网络失败 / 非 0 code / 鉴权失败）时抛出，上层降级到 MySQL FULLTEXT +
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

/**
 * Milvus 不可用（网络失败 / 非 0 code / 鉴权失败）时抛出，上层降级到 MySQL FULLTEXT + 进程内向量检索。
 */
public class MilvusUnavailableException extends RuntimeException {

    public MilvusUnavailableException(String message) {
        super(message);
    }

    public MilvusUnavailableException(String message, Throwable cause) {
        super(message, cause);
    }
}
