package com.xingtu.agent.tool;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-13] 结构化知识
// 职责：知识库检索工具：search_knowledge（READ），返回引用列表并透传 citations
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.rag.Citation;
import com.xingtu.agent.rag.HybridRetriever;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识库检索工具：search_knowledge（READ），返回引用列表并透传 citations。
 */
@Component
public class KnowledgeTools {

    private static final List<String> AGENTS = List.of("SHOPPING", "SERVICE", "OPS");

    private final HybridRetriever retriever;

    public KnowledgeTools(ToolRegistry registry, HybridRetriever retriever) {
        this.retriever = retriever;
        registry.register(new ToolRegistry.Definition("search_knowledge",
                "检索知识库（政策/手册/FAQ），参数 {query, topK?, docTypes?[]}；返回带引用的片段。",
                ToolRisk.READ, AGENTS, this::search));
    }

    private ToolResult search(Map<String, Object> args, ToolContext context) {
        String query = ToolContext.str(args, "query", context.question());
        int topK = Math.max(1, Math.min(ToolContext.intVal(args, "topK", 3), 10));
        List<String> docTypes = ToolContext.strList(args, "docTypes");
        HybridRetriever.Result result = retriever.retrieve(query, topK, docTypes, "hybrid");
        if (result.hits().isEmpty()) {
            return ToolResult.fail("知识库中没有找到与「" + query + "」相关的内容");
        }
        List<Map<String, Object>> items = new ArrayList<>();
        List<Citation> citations = new ArrayList<>();
        int index = 1;
        for (HybridRetriever.HitDetail hit : result.hits()) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("index", index++);
            item.put("chunkId", hit.chunkId());
            item.put("documentId", hit.documentId());
            item.put("title", hit.title());
            item.put("snippet", hit.content().length() > 300 ? hit.content().substring(0, 300) : hit.content());
            item.put("score", hit.score());
            items.add(item);
            citations.add(new Citation(hit.documentId(), hit.chunkId(), hit.title(), hit.content(),
                    hit.score()));
        }
        return ToolResult.ok("知识库命中 " + items.size() + " 条，最相关：" + items.get(0).get("title"),
                items, citations);
    }
}
