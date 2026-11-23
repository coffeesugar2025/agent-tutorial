package com.xingtu.agent.rag;

import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.infra.MilvusRestClient;
import com.xingtu.agent.infra.VectorStore;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Milvus 向量库实现（REST v2）。任何失败都抛 {@link com.xingtu.agent.infra.MilvusUnavailableException}，
 * 由 HybridRetriever 降级到进程内向量检索。
 */
@Component
public class MilvusVectorStore implements VectorStore {

    private final MilvusRestClient client;
    private final AppProperties props;

    public MilvusVectorStore(MilvusRestClient client, AppProperties props) {
        this.client = client;
        this.props = props;
    }

    @Override
    public String backend() {
        return "milvus";
    }

    @Override
    public boolean available() {
        return props.getMilvus().isEnabled() && client.healthy();
    }

    @Override
    public void put(Scope scope, long id, long documentId, float[] vector) {
        List<Map<String, Object>> rows = new ArrayList<>();
        rows.add(row(id, documentId, vector));
        putAll(scope, rows);
    }

    /** 批量写入，避免逐条 HTTP 调用。 */
    public void putAll(Scope scope, List<Map<String, Object>> rows) {
        if (rows == null || rows.isEmpty()) {
            return;
        }
        String collection = collectionName(scope);
        client.ensureCollection(collection, props.getEmbedding().getDim());
        client.insert(collection, rows);
    }

    public Map<String, Object> row(long id, long documentId, float[] vector) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("id", id);
        row.put("vector", vector);
        row.put("document_id", documentId);
        row.put("ref_id", id);
        return row;
    }

    @Override
    public List<Hit> search(Scope scope, float[] vector, int topK, Long documentId) {
        String filter = documentId == null ? null : "document_id == " + documentId;
        List<MilvusRestClient.MilvusHit> raw = client.search(collectionName(scope), vector, topK, filter,
                List.of("document_id", "ref_id"));
        List<Hit> hits = new ArrayList<>();
        for (MilvusRestClient.MilvusHit hit : raw) {
            hits.add(new Hit(hit.id(), longValue(hit.fields().get("document_id")), hit.score()));
        }
        return hits;
    }

    @Override
    public void deleteByDocument(Scope scope, long documentId) {
        String collection = collectionName(scope);
        if (!client.hasCollection(collection)) {
            return;
        }
        client.deleteByFilter(collection, "document_id == " + documentId);
    }

    public void deleteByIds(Scope scope, List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return;
        }
        StringBuilder filter = new StringBuilder("id in [");
        for (int i = 0; i < ids.size(); i++) {
            filter.append(i == 0 ? "" : ",").append(ids.get(i));
        }
        filter.append("]");
        String collection = collectionName(scope);
        if (!client.hasCollection(collection)) {
            return;
        }
        client.deleteByFilter(collection, filter.toString());
    }

    public String collectionName(Scope scope) {
        return props.getMilvus().getCollectionPrefix() + "_" + scope.key();
    }

    private long longValue(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text) {
            try {
                return Long.parseLong(text);
            } catch (NumberFormatException e) {
                return 0L;
            }
        }
        return 0L;
    }
}
