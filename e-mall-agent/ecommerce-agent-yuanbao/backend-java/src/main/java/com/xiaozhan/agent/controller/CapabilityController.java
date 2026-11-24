package com.xiaozhan.agent.controller;

import com.xiaozhan.agent.dto.ApiDtos.CapabilityResponse;
import com.xiaozhan.agent.service.LlmRouter;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/v2")
public class CapabilityController {
    private final LlmRouter router;
    public CapabilityController(LlmRouter router) { this.router = router; }

    @GetMapping("/capabilities")
    public CapabilityResponse capabilities() {
        return new CapabilityResponse("java", "langchain4j 1.24.0 / Spring Boot 3 / JDK17", 10,
                Map.of("planning", "ReAct / Plan-and-Solve", "workflow", "状态机 5 节点",
                        "multi_agent", "Supervisor + 3 专家", "hitl", "三粒度 + 超时默认拒绝",
                        "rag", "Milvus + ACL + 混合检索 + Rerank + 引用", "infra", "MySQL/Redis/RabbitMQ/Milvus",
                        "models", router.providers()));
    }

    @PostMapping("/plan")
    public Map<String, Object> plan(@RequestBody Map<String, Object> body) {
        return new com.xiaozhan.agent.service.PlanningService()
                .plan(String.valueOf(body.getOrDefault("message", "")),
                      String.valueOf(body.getOrDefault("strategy", "react")));
    }
    @PostMapping("/workflow/run")
    public Map<String, Object> workflow(@RequestBody Map<String, Object> body) {
        return new com.xiaozhan.agent.service.PlanningService()
                .workflow(String.valueOf(body.getOrDefault("message", "")));
    }
    @PostMapping("/multi-agent/chat")
    public Map<String, Object> multiAgent(@RequestBody Map<String, Object> body) {
        return new com.xiaozhan.agent.service.PlanningService()
                .multiAgent(String.valueOf(body.getOrDefault("message", "")));
    }
    @PostMapping("/models/route")
    public Map<String, Object> route(@RequestBody Map<String, Object> body) {
        return router.route(String.valueOf(body.getOrDefault("intent", "other")), null, null,
                Boolean.TRUE.equals(body.get("sensitive")), null, null);
    }
}
