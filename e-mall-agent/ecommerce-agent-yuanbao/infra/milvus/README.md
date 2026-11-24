# Milvus 向量库

compose 起 `milvus-standalone`（依赖 etcd + minio），集合 `ecommerce_chunks`：

| 字段 | 类型 | 说明 |
|---|---|---|
| chunk_id | VARCHAR(160) PK | 与内容绑定，内容不变则复用 |
| doc_id / version | VARCHAR / INT | 版本化，支持增量与撤销 |
| embedding | FLOAT_VECTOR(1024) | 由 `EmbeddingModel` 产出（生产用 bge-m3 / text-embedding-v3） |
| text | VARCHAR | 原文，用于引用回溯 |
| acl_tenant / acl_roles | VARCHAR | **先过滤再检索**，避免越权召回 |

索引：HNSW（M=16, efConstruction=200），检索 ef=64；标量字段建 inverted index。
Python 侧 `app/infra/adapters.py::MilvusAdapter`、Java 侧 `RagService` 共用同一集合契约。
离线/未部署时自动降级到进程内 `InMemoryVectorStore`，接口不变。
