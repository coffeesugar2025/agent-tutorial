package com.xingtu.agent.infra;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.config.AppProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Milvus REST v2 客户端（不引入 Milvus SDK）。
 *
 * <p>端点：{@code POST {base}/v2/vectordb/collections/create|has|describe}、
 * {@code /v2/vectordb/entities/insert|search|query|delete}；
 * 鉴权头 {@code Authorization: Bearer <MILVUS_TOKEN>}。</p>
 *
 * <p>REST 端口与 gRPC 端口不同：契约中的 MILVUS_PORT=19530 是 gRPC，
 * REST 默认走 9091（可用 MILVUS_REST_PORT 覆盖）。</p>
 */
@Component
public class MilvusRestClient {

    private static final Logger log = LoggerFactory.getLogger(MilvusRestClient.class);
    private static final ObjectMapper MAPPER = JsonUtil.mapper();

    private final AppProperties props;
    private final HttpClient httpClient;
    private final String baseUrl;
    private volatile long lastHealthAt = 0L;
    private volatile boolean lastHealth = false;

    public MilvusRestClient(AppProperties props) {
        this.props = props;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofMillis(props.getMilvus().getTimeoutMs()))
                .build();
        this.baseUrl = "http://" + props.getMilvus().getHost() + ":" + props.getMilvus().getRestPort();
    }

    public String baseUrl() {
        return baseUrl;
    }

    /** 轻量健康检查，缓存 10s 避免每次请求都打 Milvus。 */
    public boolean healthy() {
        if (!props.getMilvus().isEnabled()) {
            return false;
        }
        long now = System.currentTimeMillis();
        if (now - lastHealthAt < 10_000L) {
            return lastHealth;
        }
        try {
            hasCollection(props.getMilvus().getCollectionPrefix() + "_knowledge");
            lastHealth = true;
        } catch (RuntimeException e) {
            lastHealth = false;
            log.debug("Milvus 健康检查失败: {}", e.getMessage());
        }
        lastHealthAt = now;
        return lastHealth;
    }

    public boolean hasCollection(String collectionName) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("collectionName", collectionName);
        JsonNode root = post("/v2/vectordb/collections/has", body);
        JsonNode data = root.path("data");
        if (data.isObject()) {
            return data.path("has").asBoolean(false);
        }
        return data.asBoolean(false);
    }

    public void createCollection(String collectionName, int dim) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("collectionName", collectionName);
        ObjectNode schema = body.putObject("schema");
        schema.put("autoId", false);
        schema.put("enableDynamicField", true);
        ArrayNode fields = schema.putArray("fields");
        fields.add(field("id", "Int64", true, 0));
        fields.add(field("vector", "FloatVector", false, dim));
        fields.add(field("document_id", "Int64", false, 0));
        fields.add(field("ref_id", "Int64", false, 0));
        ArrayNode indexParams = body.putArray("indexParams");
        ObjectNode index = indexParams.addObject();
        index.put("fieldName", "vector");
        index.put("indexName", "vector_idx");
        index.put("metricType", "COSINE");
        index.put("indexType", "AUTOINDEX");
        post("/v2/vectordb/collections/create", body);
    }

    public void ensureCollection(String collectionName, int dim) {
        if (!props.getMilvus().isEnabled()) {
            throw new MilvusUnavailableException("Milvus 已通过 MILVUS_ENABLED=false 关闭");
        }
        try {
            if (hasCollection(collectionName)) {
                return;
            }
            createCollection(collectionName, dim);
            log.info("已创建 Milvus 集合 {} (dim={})", collectionName, dim);
        } catch (MilvusUnavailableException e) {
            throw e;
        } catch (RuntimeException e) {
            throw new MilvusUnavailableException("创建 Milvus 集合失败: " + collectionName, e);
        }
    }

    public void insert(String collectionName, List<Map<String, Object>> rows) {
        if (rows == null || rows.isEmpty()) {
            return;
        }
        ObjectNode body = MAPPER.createObjectNode();
        body.put("collectionName", collectionName);
        ArrayNode data = body.putArray("data");
        for (Map<String, Object> row : rows) {
            ObjectNode item = data.addObject();
            for (Map.Entry<String, Object> entry : row.entrySet()) {
                putValue(item, entry.getKey(), entry.getValue());
            }
        }
        post("/v2/vectordb/entities/insert", body);
    }

    public List<MilvusHit> search(String collectionName, float[] vector, int limit, String filter,
                                  List<String> outputFields) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("collectionName", collectionName);
        ArrayNode data = body.putArray("data");
        ArrayNode one = data.addArray();
        for (float value : vector) {
            one.add(value);
        }
        body.put("annsField", "vector");
        body.put("limit", limit);
        if (filter != null && !filter.isBlank()) {
            body.put("filter", filter);
        }
        if (outputFields != null && !outputFields.isEmpty()) {
            ArrayNode fields = body.putArray("outputFields");
            for (String field : outputFields) {
                fields.add(field);
            }
        }
        JsonNode root = post("/v2/vectordb/entities/search", body);
        List<MilvusHit> hits = new ArrayList<>();
        for (JsonNode row : extractRows(root)) {
            long id = row.path("id").asLong(0L);
            double score = row.path("distance").asDouble(row.path("score").asDouble(0d));
            Map<String, Object> fields = new LinkedHashMap<>();
            Iterator<String> names = row.fieldNames();
            while (names.hasNext()) {
                String name = names.next();
                if (!"id".equals(name) && !"distance".equals(name)) {
                    fields.put(name, nodeToValue(row.get(name)));
                }
            }
            hits.add(new MilvusHit(id, score, fields));
        }
        return hits;
    }

    public List<Map<String, Object>> query(String collectionName, String filter, List<String> outputFields,
                                           int limit) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("collectionName", collectionName);
        body.put("filter", filter == null ? "" : filter);
        body.put("limit", limit);
        if (outputFields != null && !outputFields.isEmpty()) {
            ArrayNode fields = body.putArray("outputFields");
            for (String field : outputFields) {
                fields.add(field);
            }
        }
        JsonNode root = post("/v2/vectordb/entities/query", body);
        List<Map<String, Object>> rows = new ArrayList<>();
        for (JsonNode row : extractRows(root)) {
            Map<String, Object> item = new LinkedHashMap<>();
            Iterator<String> names = row.fieldNames();
            while (names.hasNext()) {
                String name = names.next();
                item.put(name, nodeToValue(row.get(name)));
            }
            rows.add(item);
        }
        return rows;
    }

    public void deleteByFilter(String collectionName, String filter) {
        ObjectNode body = MAPPER.createObjectNode();
        body.put("collectionName", collectionName);
        body.put("filter", filter);
        post("/v2/vectordb/entities/delete", body);
    }

    /** 记录类型：{id, score, fields}。 */
    public record MilvusHit(long id, double score, Map<String, Object> fields) {
    }

    private JsonNode post(String path, ObjectNode body) {
        String json = body.toString();
        HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + path))
                .timeout(Duration.ofMillis(props.getMilvus().getTimeoutMs()))
                .header("Content-Type", "application/json")
                .header("Authorization", "Bearer " + props.getMilvus().getToken())
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .build();
        try {
            HttpResponse<String> response = httpClient.send(request,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new MilvusUnavailableException("Milvus HTTP " + response.statusCode() + " " + path
                        + " body=" + abbreviate(response.body()));
            }
            JsonNode root = MAPPER.readTree(response.body());
            int code = root.path("code").asInt(0);
            if (code != 0 && code != 200) {
                throw new MilvusUnavailableException("Milvus code=" + code + " path=" + path
                        + " message=" + root.path("message").asText(""));
            }
            return root;
        } catch (MilvusUnavailableException e) {
            throw e;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new MilvusUnavailableException("Milvus 调用被中断: " + path, e);
        } catch (Exception e) {
            throw new MilvusUnavailableException("Milvus 调用失败: " + path + " " + e.getMessage(), e);
        }
    }

    private ObjectNode field(String name, String dataType, boolean primary, int dim) {
        ObjectNode node = MAPPER.createObjectNode();
        node.put("fieldName", name);
        node.put("dataType", dataType);
        if (primary) {
            node.put("isPrimary", true);
        }
        if (dim > 0) {
            ObjectNode params = node.putObject("elementTypeParams");
            params.put("dim", dim);
        }
        return node;
    }

    private void putValue(ObjectNode item, String key, Object value) {
        if (value instanceof Float[] floats) {
            ArrayNode array = item.putArray(key);
            for (Float f : floats) {
                array.add(f);
            }
            return;
        }
        if (value instanceof float[] floats) {
            ArrayNode array = item.putArray(key);
            for (float f : floats) {
                array.add(f);
            }
            return;
        }
        if (value instanceof Number number) {
            item.put(key, number.doubleValue());
            return;
        }
        if (value == null) {
            item.putNull(key);
            return;
        }
        item.put(key, String.valueOf(value));
    }

    private List<JsonNode> extractRows(JsonNode root) {
        List<JsonNode> rows = new ArrayList<>();
        JsonNode data = root.path("data");
        if (data.isArray()) {
            data.forEach(rows::add);
            return rows;
        }
        JsonNode nested = data.path("data");
        if (nested.isArray()) {
            nested.forEach(rows::add);
        }
        return rows;
    }

    private Object nodeToValue(JsonNode node) {
        if (node == null || node.isNull()) {
            return null;
        }
        if (node.isNumber()) {
            return node.numberValue();
        }
        if (node.isBoolean()) {
            return node.booleanValue();
        }
        if (node.isArray()) {
            List<Object> values = new ArrayList<>();
            node.forEach(child -> values.add(nodeToValue(child)));
            return values;
        }
        if (node.isObject()) {
            return MAPPER.convertValue(node, Map.class);
        }
        return node.asText();
    }

    private String abbreviate(String text) {
        if (text == null) {
            return "";
        }
        return text.length() <= 300 ? text : text.substring(0, 300) + "...";
    }
}
