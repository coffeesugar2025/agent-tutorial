package com.xingtu.agent.api.dto;

import java.util.List;
import java.util.Map;

/**
 * GET /api/v1/meta/capabilities 响应 DTO（docs/03-API契约.md 第 7 节）。
 * 前端据此显示/隐藏实验性入口。
 */
public final class MetaDtos {

    private MetaDtos() {
    }

    /** 模型能力。 */
    public record LlmCapabilityVO(String primary, List<String> fallbacks) {
    }

    /** 能力声明。 */
    public record CapabilitiesVO(String backend, String version, Map<String, Boolean> features,
                                 LlmCapabilityVO llm) {
    }
}
