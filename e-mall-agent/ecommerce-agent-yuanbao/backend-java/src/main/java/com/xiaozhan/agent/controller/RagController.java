package com.xiaozhan.agent.controller;

import com.xiaozhan.agent.dto.ApiDtos.RagRequest;
import com.xiaozhan.agent.service.RagService;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/v2/rag")
public class RagController {
    private final RagService rag;
    public RagController(RagService rag) { this.rag = rag; }

    @PostMapping("/query")
    public Map<String, Object> query(@RequestBody RagRequest req) {
        return rag.query(req.question(), req.mode() == null ? "all" : req.mode(),
                req.topK() == 0 ? 5 : req.topK(),
                req.userId() == null ? "u_1001" : req.userId(),
                req.tenantId() == null ? "t_default" : req.tenantId(),
                req.roles() == null ? List.of("user") : req.roles());
    }
    @PostMapping("/text2sql")
    public Map<String, Object> text2sql(@RequestBody Map<String, Object> b) {
        return rag.text2sql(String.valueOf(b.getOrDefault("question", ""))); }
    @GetMapping("/stats")
    public Map<String, Object> stats() { return Map.of("collection", "ecommerce_chunks",
            "index", "HNSW/M=16/efConstruction=200", "vector_db", "Milvus"); }
}
