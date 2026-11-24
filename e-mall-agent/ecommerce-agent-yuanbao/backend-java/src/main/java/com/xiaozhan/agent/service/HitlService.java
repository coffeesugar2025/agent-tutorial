package com.xiaozhan.agent.service;

import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/** 3.6：事前批准 / 事中打断 / 事后审核 + 超时默认拒绝 + 自包含交接摘要。 */
@Service
public class HitlService {
    private final Map<String, Map<String, Object>> items = new ConcurrentHashMap<>();

    public Map<String, Object> submit(String kind, String tool, Map<String, Object> args,
                                      String traceId, long timeoutSeconds) {
        String id = "rev_" + UUID.randomUUID().toString().substring(0, 8);
        String summary = "【待审批】工具=" + tool + "；参数=" + args + "；轨迹=" + traceId
                + "。该操作不可自动执行，请核对金额与归属后批准/拒绝/改写。";
        Map<String, Object> it = new ConcurrentHashMap<>();
        it.put("id", id); it.put("kind", kind); it.put("summary", summary);
        it.put("status", "pending"); it.put("created_at", Instant.now().toString());
        it.put("timeout_seconds", timeoutSeconds); it.put("trace_id", traceId);
        items.put(id, it);
        return it;
    }

    public Map<String, Object> scanTimeouts() {
        List<String> rejected = new ArrayList<>();
        for (var e : items.entrySet()) {
            Map<String, Object> it = e.getValue();
            if (!"pending".equals(it.get("status"))) continue;
            long created = Instant.parse((String) it.get("created_at")).toEpochMilli();
            if (System.currentTimeMillis() - created > ((Number) it.get("timeout_seconds")).longValue() * 1000L) {
                it.put("status", "rejected"); it.put("decision", "timeout_default_reject");
                rejected.add(e.getKey());
            }
        }
        return Map.of("scanned", items.size(), "expired_rejected", rejected, "default_action", "reject");
    }

    public Map<String, Object> decide(String id, String decision, String reviewer, String note) {
        Map<String, Object> it = items.get(id);
        if (it == null) return Map.of("ok", false, "error", "不存在");
        if (!"pending".equals(it.get("status"))) return Map.of("ok", false, "error", "已处理");
        it.put("status", decision); it.put("decided_by", reviewer); it.put("note", note);
        return Map.of("ok", true, "item", it, "context_injection",
                Map.of("role", "system", "content", "人工审批结果：" + decision
                        + "；审核人=" + reviewer + "；备注=" + note + "。请据此继续，不得重复提交。"));
    }

    public Map<String, Object> stats() { return Map.of("items", items.size()); }
}
