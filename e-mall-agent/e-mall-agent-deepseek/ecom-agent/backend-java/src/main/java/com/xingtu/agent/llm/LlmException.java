package com.xingtu.agent.llm;

/**
 * 单次模型调用失败（网络 / 4xx / 5xx / 解析失败），由 ModelRouter 捕获触发降级。
 */
public class LlmException extends RuntimeException {

    public LlmException(String message) {
        super(message);
    }

    public LlmException(String message, Throwable cause) {
        super(message, cause);
    }
}
