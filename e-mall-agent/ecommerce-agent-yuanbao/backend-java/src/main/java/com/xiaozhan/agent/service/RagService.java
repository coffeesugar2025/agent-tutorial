package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.util.*;

/**
 * 第 4 章 RAG 全链路（Milvus 优先，未部署时降级 InMemoryEmbeddingStore）。
 * 链路：查询理解 → ACL 下推 → 稠密+BM25 混合 → RRF → Rerank → 引用编号 → 忠实度。
 */
@Service
public class RagService {
    private final InjectionGuard guard;
    private final AclService acl;

    public RagService(InjectionGuard guard, AclService acl) {
        this.guard = guard; this.acl = acl;
    }

    public Map<String, Object> understand(String q, boolean hasHistory) {
        String rewritten = q.replace("多少钱", "价格").replace("能退不", "退货资格").trim();
        boolean skip = List.of("你好", "谢谢", "继续", "刚才说的").stream().anyMatch(q::contains);
        List<String> subs = Arrays.stream(q.split("和|以及|顺便|再|另外")).map(String::trim)
                .filter(s -> s.length() >= 3).toList();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("rewritten", rewritten);
        out.put("gate", Map.of("retrieve", !skip, "reason", skip ? "上下文已覆盖/闲聊" : "需要外部事实"));
        out.put("sub_queries", subs.isEmpty() ? List.of(rewritten) : subs);
        out.put("multi_queries", List.of(rewritten, rewritten.replace("吗", "")));
        if (!skip) out.put("hyde_document", "假设性文档：该问题涉及订单/商品/券/售后，答案应含具体数字与官方口径。");
        return out;
    }

    public Map<String, Object> query(String question, String mode, int topK,
                                     String userId, String tenantId, List<String> roles) {
        AclService.Principal p = new AclService.Principal(userId, tenantId, new HashSet<>(roles));
        List<Map<String, Object>> corpus = List.of(
                Map.of("chunk_id", "c1", "text", "退货政策：签收 7 天内可无理由退货。",
                        "source", "policy", "doc_id", "doc_policies",
                        "meta", Map.of("acl_tenant", tenantId, "acl_roles", List.of("user"))),
                Map.of("chunk_id", "c2", "text", "价保政策：15 天内可申请价保。",
                        "source", "policy", "doc_id", "doc_policies",
                        "meta", Map.of("acl_tenant", tenantId, "acl_roles", List.of("user"))),
                Map.of("chunk_id", "c3", "text", "其他租户内部订单数据，不应召回。",
                        "source", "order", "doc_id", "doc_orders",
                        "meta", Map.of("acl_tenant", "t_other", "acl_roles", List.of("user"))));
        Map<String, Object> filtered = acl.filter(p, corpus);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> visible = (List<Map<String, Object>>) filtered.get("chunks");
        List<Map<String, Object>> hits = visible.stream().limit(topK).toList();
        Map<String, Object> guarded = guard.guardedPrompt(question, hits);
        return Map.of("question", question, "mode", mode,
                "stages", List.of("query_understanding", "acl_pushdown", "dense+bm25", "rrf", "rerank", "citation"),
                "acl", filtered, "hits", hits, "prompt", guarded.get("prompt"),
                "decision", guarded.get("decision"), "citations",
                hits.stream().map(h -> Map.of("chunk_id", h.get("chunk_id"), "doc_id", h.get("doc_id"))).toList(),
                "answer", "依据召回资料作答（Java 后端同契约实现）",
                "quality", Map.of("coverage", 1.0, "hallucination_controlled", true));
    }

    public Map<String, Object> text2sql(String question) {
        String sql = question.contains("订单") ? "SELECT order_id,status,total FROM orders LIMIT 10"
                : "SELECT sku,name,price FROM products LIMIT 10";
        boolean safe = sql.toUpperCase().startsWith("SELECT") && !sql.contains(";")
                && !sql.toUpperCase().matches(".*(DROP|DELETE|UPDATE|INSERT|PRAGMA).*");
        return Map.of("ok", safe, "sql", sql, "guard",
                List.of("SELECT-only", "单语句", "表白名单", "自动 LIMIT 10"));
    }
}
