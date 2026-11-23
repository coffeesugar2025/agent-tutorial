package com.xingtu.agent.llm;

import java.util.List;

/**
 * 模型供应商抽象。所有实现都是 OpenAI 兼容的 /chat/completions 语义（mock 除外）。
 */
public interface LlmProvider {

    record Message(String role, String content) {
        public static Message system(String content) {
            return new Message("system", content);
        }

        public static Message user(String content) {
            return new Message("user", content);
        }

        public static Message assistant(String content) {
            return new Message("assistant", content);
        }
    }

    record Request(List<Message> messages, double temperature, int maxTokens) {
        public String lastUserContent() {
            for (int i = messages.size() - 1; i >= 0; i--) {
                Message message = messages.get(i);
                if ("user".equals(message.role())) {
                    return message.content();
                }
            }
            return "";
        }
    }

    record Result(String text, int promptTokens, int completionTokens, String provider, String model,
                  long latencyMs) {
        public int totalTokens() {
            return promptTokens + completionTokens;
        }
    }

    String name();

    String model();

    boolean configured();

    Result chat(Request request);
}
