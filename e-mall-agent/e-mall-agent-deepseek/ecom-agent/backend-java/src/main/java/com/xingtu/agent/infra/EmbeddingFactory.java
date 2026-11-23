package com.xingtu.agent.infra;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.rag.EmbeddingModel;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;

/**
 * 远程 embedding 工厂：dashscope / openai / ollama 都兼容 OpenAI /embeddings 协议。
 */
public final class EmbeddingFactory {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingFactory.class);
    private static final ObjectMapper MAPPER = JsonUtil.mapper();

    private EmbeddingFactory() {
    }

    public static EmbeddingModel create(AppProperties props) {
        String provider = props.getEmbedding().getProvider();
        if (provider == null || provider.isBlank() || "hash".equalsIgnoreCase(provider)) {
            return new HashEmbeddingModel(props);
        }
        String baseUrl = resolveBaseUrl(props, provider);
        String apiKey = props.getEmbedding().getApiKey();
        if (apiKey == null || apiKey.isBlank()) {
            log.warn("EMBEDDING_PROVIDER={} 但未配置 API Key，自动降级为 hash 向量", provider);
            return new HashEmbeddingModel(props);
        }
        return new HttpEmbeddingModel(baseUrl, apiKey, props.getEmbedding().getModel(),
                props.getEmbedding().getDim(), provider);
    }

    private static String resolveBaseUrl(AppProperties props, String provider) {
        String configured = props.getEmbedding().getBaseUrl();
        if (configured != null && !configured.isBlank()) {
            return trimSlash(configured);
        }
        if ("dashscope".equalsIgnoreCase(provider)) {
            return "https://dashscope.aliyuncs.com/compatible-mode/v1";
        }
        if ("ollama".equalsIgnoreCase(provider)) {
            String host = props.getLlm().getProviders().containsKey("ollama")
                    ? props.getLlm().getProviders().get("ollama").getBaseUrl()
                    : "http://localhost:11434/v1";
            return trimSlash(host);
        }
        return "https://api.openai.com/v1";
    }

    private static String trimSlash(String url) {
        return url.endsWith("/") ? url.substring(0, url.length() - 1) : url;
    }

    /** OpenAI 兼容 /embeddings 客户端。 */
    public static final class HttpEmbeddingModel implements EmbeddingModel {

        private final String baseUrl;
        private final String apiKey;
        private final String model;
        private final int dim;
        private final String provider;
        private final HttpClient httpClient;

        public HttpEmbeddingModel(String baseUrl, String apiKey, String model, int dim, String provider) {
            this.baseUrl = baseUrl;
            this.apiKey = apiKey;
            this.model = model;
            this.dim = dim;
            this.provider = provider;
            this.httpClient = HttpClient.newBuilder()
                    .connectTimeout(Duration.ofSeconds(5))
                    .build();
        }

        @Override
        public int dim() {
            return dim;
        }

        @Override
        public String provider() {
            return provider;
        }

        @Override
        public float[] embed(String text) {
            ObjectNode body = MAPPER.createObjectNode();
            body.put("model", model);
            body.put("input", text == null ? "" : text);
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + "/embeddings"))
                    .timeout(Duration.ofSeconds(20))
                    .header("Content-Type", "application/json")
                    .header("Authorization", "Bearer " + apiKey)
                    .POST(HttpRequest.BodyPublishers.ofString(body.toString(), StandardCharsets.UTF_8))
                    .build();
            try {
                HttpResponse<String> response = httpClient.send(request,
                        HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
                if (response.statusCode() < 200 || response.statusCode() >= 300) {
                    throw new IllegalStateException("embedding HTTP " + response.statusCode());
                }
                JsonNode root = MAPPER.readTree(response.body());
                JsonNode embedding = root.path("data").path(0).path("embedding");
                if (!embedding.isArray() || embedding.isEmpty()) {
                    throw new IllegalStateException("embedding 响应缺少 data[0].embedding");
                }
                ArrayNode array = (ArrayNode) embedding;
                float[] vector = new float[array.size()];
                for (int i = 0; i < array.size(); i++) {
                    vector[i] = (float) array.get(i).asDouble();
                }
                HashEmbeddingModel.normalize(vector);
                return vector;
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new IllegalStateException("embedding 调用被中断", e);
            } catch (Exception e) {
                throw new IllegalStateException("embedding 调用失败: " + e.getMessage(), e);
            }
        }
    }
}
