"""RAG 与知识工程包。

  chunking      文档解析 / 切片 / 版本管理 / 增量索引 / 撤销
  vectorstore   Embedding / 向量库 / BM25 / 混合检索(RRF) / Rerank / 向量库适配器契约
  knowledge     知识图谱 / Ontology / Text2Cypher / GraphRAG / Neo4j 适配器契约
  text2sql      受限 Text2SQL（只读 SELECT + SQL Guard + sqlite 执行）
  pipeline      端到端 RAG Pipeline / Prompt 拼接 / 引用质量评估 / 幻觉控制

基础层 → 进阶层 → 高阶层全部落地；所有检索在进程内可离线跑，外部向量库/图数据库
以适配器契约形式给出，替换实现即可，不改 Pipeline 接口。
"""
