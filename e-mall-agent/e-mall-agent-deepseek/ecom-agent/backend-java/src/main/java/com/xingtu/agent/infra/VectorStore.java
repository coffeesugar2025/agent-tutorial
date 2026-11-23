package com.xingtu.agent.infra;

import java.util.List;

/**
 * 向量存储抽象：Milvus 与进程内实现共用同一接口，便于降级。
 */
public interface VectorStore {

    /** 业务集合：实际 Milvus 集合名为 {MILVUS_COLLECTION_PREFIX}_{key}。 */
    enum Scope {
        KNOWLEDGE("knowledge"),
        PRODUCT("product"),
        MEMORY("memory");

        private final String key;

        Scope(String key) {
            this.key = key;
        }

        public String key() {
            return key;
        }
    }

    record Hit(long id, long documentId, double score) {
    }

    String backend();

    boolean available();

    void put(Scope scope, long id, long documentId, float[] vector);

    List<Hit> search(Scope scope, float[] vector, int topK, Long documentId);

    void deleteByDocument(Scope scope, long documentId);
}
