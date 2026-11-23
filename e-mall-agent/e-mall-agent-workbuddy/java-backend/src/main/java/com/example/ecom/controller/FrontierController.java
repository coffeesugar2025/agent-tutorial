package com.example.ecom.controller;

import com.example.ecom.rag.RetrievalService;
import com.example.ecom.security.InjectionScanner;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** 可选前沿端点：输入注入扫描与 RAG 查询改写（对齐 Python /api/frontier/* 子集）。 */
@RestController
@RequestMapping("/api/frontier")
public class FrontierController {

    private final InjectionScanner scanner;
    private final RetrievalService retrieval;

    public FrontierController(InjectionScanner scanner, RetrievalService retrieval) {
        this.scanner = scanner;
        this.retrieval = retrieval;
    }

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ScanRequest(String text) {}

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record RewriteRequest(String query, String mode) {}

    @PostMapping("/security/scan")
    public Map<String, Object> scan(@RequestBody ScanRequest request) {
        var result = scanner.scan(request.text());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("detected", result.detected());
        out.put("score", result.score());
        out.put("matched", result.matched());
        out.put("risk_level", result.score() >= 0.7 ? "high" : result.score() >= 0.34 ? "medium" : "low");
        out.put("action", result.detected() ? "block_instructions" : "allow");
        return out;
    }

    @PostMapping("/rag/rewrite")
    public Map<String, Object> rewrite(@RequestBody RewriteRequest request) {
        String q = request.query() == null ? "" : request.query().trim();
        String mode = request.mode() == null ? "multi" : request.mode();
        List<String> queries = switch (mode) {
            case "hyde" -> List.of("假设答案：" + q, q);
            case "stepback" -> List.of("关于「" + q + "」的通用规则是什么？", q);
            case "decompose" -> List.of(q + " 的定义", q + " 的条件", q + " 的注意事项");
            default -> List.of(q, q + " 政策", q + " 流程");
        };
        return Map.of("mode", mode, "queries", queries,
                "hits", retrieval.retrieve(q, 3).stream().map(h -> h.source()).toList());
    }
}
