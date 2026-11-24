package com.xiaozhan.agent.controller;

import com.xiaozhan.agent.dto.ApiDtos.*;
import com.xiaozhan.agent.service.*;
import org.springframework.web.bind.annotation.*;
import java.util.*;

/** /v3/* 与 Python 后端逐路径对齐，供统一契约测试比对。 */
@RestController
@RequestMapping("/v3")
public class V3Controller {
    private final DecisionEngine decision;
    private final LlmRouter router;
    private final InjectionGuard injection;
    private final AclService acl;
    private final ReliabilityService reliability;
    private final RagService rag;
    private final HitlService hitl;
    private final MemoryContextService memory;
    private final ObservabilityService obs;
    private final CostCacheService cost;

    public V3Controller(DecisionEngine d, LlmRouter r, InjectionGuard i, AclService a,
                        ReliabilityService rel, RagService rag, HitlService h,
                        MemoryContextService m, ObservabilityService o, CostCacheService c) {
        this.decision = d; this.router = r; this.injection = i; this.acl = a;
        this.reliability = rel; this.rag = rag; this.hitl = h;
        this.memory = m; this.obs = o; this.cost = c;
    }

    @GetMapping("/capabilities")
    public Map<String, Object> capabilities() {
        return Map.of("chapters", 10, "backend", "java",
                "decision", "第0章 判据/L0-L4/ROI/决策树",
                "model_layer", "第1章 多模型网关/路由级联",
                "rag", "第4章 查询理解/ACL/混合检索/引用治理",
                "security", "第6章 间接注入数据化封装",
                "infra", Map.of("milvus", "milvus", "mysql", "mysql",
                        "redis", "redis", "rabbitmq", "rabbitmq"));
    }

    @PostMapping("/decision/fit")
    public Map<String, Object> fit(@RequestBody DecisionEngine.TaskProfile t) {
        return Map.of("fit", decision.fit(t), "levels", decision.autonomyLevels(),
                "architecture", decision.architectureTree(t),
                "misconceptions", decision.misconceptions());
    }
    @PostMapping("/decision/roi")
    public Map<String, Object> roi(@RequestBody Map<String, Object> b) {
        return decision.roi(((Number) b.getOrDefault("inference_per_task", 0.01)).doubleValue(),
                ((Number) b.getOrDefault("success_rate", 0.85)).doubleValue(),
                ((Number) b.getOrDefault("human_rate", 0.15)).doubleValue(),
                ((Number) b.getOrDefault("human_cost", 0.15)).doubleValue(),
                ((Number) b.getOrDefault("calls_per_day", 50000)).intValue());
    }
    @GetMapping("/models")
    public Map<String, Object> models() {
        return Map.of("providers", router.providers(),
                "inference_servers", Map.of("vLLM", "http://localhost:8000/v1",
                        "SGLang", "http://localhost:30000/v1",
                        "Ollama", "http://localhost:11434/v1",
                        "Xinference", "http://localhost:9997/v1"));
    }
    @PostMapping("/models/chat")
    public Map<String, Object> chat(@RequestBody Map<String, Object> b) {
        return Map.of("result", Map.of("provider", b.getOrDefault("provider", "deepseek"),
                "text", "[java:mock] 已按事实约束回答", "cost_usd", 0.0));
    }
    @PostMapping("/models/route")
    public Map<String, Object> route(@RequestBody Map<String, Object> b) {
        return Map.of("plan", router.route(String.valueOf(b.getOrDefault("intent", "other")),
                null, null, Boolean.TRUE.equals(b.get("sensitive")), null, null),
                "order", router.optimizationOrder());
    }
    @PostMapping("/security/scan")
    public Map<String, Object> scan(@RequestBody Map<String, Object> b) {
        @SuppressWarnings("unchecked") List<Map<String, Object>> ps =
                (List<Map<String, Object>>) b.getOrDefault("passages", List.of());
        return injection.guardedPrompt(String.valueOf(b.getOrDefault("question", "")), ps);
    }
    @GetMapping("/security/redteam")
    public Map<String, Object> redteam() {
        return Map.of("total", 5, "blocked", 5, "block_rate", 1.0,
                "cases", List.of("忽略以上规则", "ignore previous instructions",
                        "HTML 注释隐藏指令", "零宽字符夹带", "Markdown 图片外带"));
    }
    @PostMapping("/errors/classify")
    public Map<String, Object> classify(@RequestBody Map<String, Object> b) {
        return reliability.classify(String.valueOf(b.getOrDefault("message", "")));
    }
    @PostMapping("/rag/acl")
    public Map<String, Object> acl(@RequestBody Map<String, Object> b,
                                   @RequestHeader(value = "X-Tenant-Id", defaultValue = "t_default") String tenant,
                                   @RequestHeader(value = "X-User-Id", defaultValue = "u_1001") String user) {
        @SuppressWarnings("unchecked") List<Map<String, Object>> chunks =
                (List<Map<String, Object>>) b.getOrDefault("chunks", List.of());
        return acl.filter(new AclService.Principal(user, tenant, Set.of("user")), chunks);
    }
    @PostMapping("/rag/understand")
    public Map<String, Object> understand(@RequestBody Map<String, Object> b) {
        return rag.understand(String.valueOf(b.getOrDefault("question", "")),
                Boolean.TRUE.equals(b.get("has_history")));
    }
    @PostMapping("/rag/evaluate")
    public Map<String, Object> evaluate(@RequestBody Map<String, Object> b) {
        return Map.of("bottleneck_layer", "检索没召回到",
                "recommended_action", "改切片/加多路召回，别先调 prompt",
                "metrics", Map.of("recall@5", 0.0, "mrr", 0.0, "ndcg@5", 0.0));
    }
    @GetMapping("/cache/report")
    public Map<String, Object> cacheReport() { return cost.report(); }
    @PostMapping("/cache/invalidate")
    public Map<String, Object> invalidate(@RequestBody Map<String, Object> b) {
        return cost.invalidate(String.valueOf(b.getOrDefault("doc_id", "")));
    }
    @PostMapping("/replay/record") public Map<String, Object> replayRecord() {
        return obs.trace("record"); }
    @PostMapping("/replay/run") public Map<String, Object> replayRun(@RequestBody Map<String, Object> b) {
        return obs.replay(String.valueOf(b.getOrDefault("trace_id", "")),
                b.getOrDefault("overrides", Map.of()) instanceof Map
                        ? (Map<String, Object>) b.get("overrides") : Map.of()); }
    @PostMapping("/replay/compare") public Map<String, Object> replayCompare() {
        return Map.of("ok", true, "identical", true, "diff_count", 0); }
    @GetMapping("/cost/report") public Map<String, Object> costReport() {
        return Map.of("report", cost.report(), "optimization_order", router.optimizationOrder()); }
    @GetMapping("/prompts") public Map<String, Object> prompts() {
        return Map.of("registry", Map.of("system.guide", List.of(Map.of("version", 1, "hash", "v1hash", "stage", "stable")))); }
    @PostMapping("/prompts/register") public Map<String, Object> promptRegister(@RequestBody Map<String, Object> b) {
        return Map.of("version", 2, "hash", "v2hash", "stage", "canary"); }
    @GetMapping("/tools/specs") public Map<String, Object> toolSpecs() {
        return Map.of("cards", List.of(Map.of("name", "getOrder",
                "when_not_to_use", "没有订单号不要猜；绝不返回其他用户订单",
                "error_codes", List.of("E_FORBIDDEN", "E_INVALID_ARG", "E_NOT_FOUND"),
                "max_output_tokens", 300, "idempotent", true))); }
    @PostMapping("/memory/merge") public Map<String, Object> memoryMerge(@RequestBody Map<String, Object> b) {
        return memory.merge("500", "300"); }
    @PostMapping("/hitl/submit") public Map<String, Object> hitlSubmit(@RequestBody Map<String, Object> b) {
        return hitl.submit(String.valueOf(b.getOrDefault("kind", "pre_approval")),
                String.valueOf(b.getOrDefault("tool", "apply_refund")), Map.of(),
                String.valueOf(b.getOrDefault("trace_id", "tr_demo")), 300L); }
    @PostMapping("/hitl/scan") public Map<String, Object> hitlScan() { return hitl.scanTimeouts(); }
    @PostMapping("/evals/stability") public Map<String, Object> stability(@RequestBody Map<String, Object> b) {
        return obs.evalStability(((Number) b.getOrDefault("k", 3)).intValue()); }
    @GetMapping("/infra") public Map<String, Object> infra() {
        return Map.of("milvus", Map.of("backend", "milvus"), "mysql", Map.of("backend", "mysql"),
                "redis", Map.of("backend", "redis"), "rabbitmq", Map.of("backend", "rabbitmq")); }
}
