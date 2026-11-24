package com.xiaozhan.agent.controller;

import com.xiaozhan.agent.service.HitlService;
import org.springframework.web.bind.annotation.*;
import java.util.*;

@RestController
@RequestMapping("/v2/approvals")
public class ApprovalController {
    private final HitlService hitl;
    public ApprovalController(HitlService h) { this.hitl = h; }
    @GetMapping public Map<String, Object> list() { return Map.of("stats", hitl.stats()); }
    @PostMapping("/submit") public Map<String, Object> submit(@RequestBody Map<String, Object> b) {
        return hitl.submit("pre_approval", String.valueOf(b.getOrDefault("tool", "apply_refund")),
                Map.of(), "tr_demo", 300L); }
    @PostMapping("/{id}/decide") public Map<String, Object> decide(@PathVariable String id,
            @RequestBody Map<String, Object> b) {
        return hitl.decide(id, String.valueOf(b.getOrDefault("decision", "approve")),
                "reviewer", String.valueOf(b.getOrDefault("note", ""))); }
    @PostMapping("/{id}/resume") public Map<String, Object> resume(@PathVariable String id) {
        return Map.of("status", "executed", "idempotent_hit", false, "approval_id", id); }
}
