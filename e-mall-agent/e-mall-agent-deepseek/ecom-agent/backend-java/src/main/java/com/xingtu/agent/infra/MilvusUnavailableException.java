package com.xingtu.agent.infra;

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
