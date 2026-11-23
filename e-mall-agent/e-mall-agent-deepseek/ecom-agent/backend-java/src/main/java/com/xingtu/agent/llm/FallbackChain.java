package com.xingtu.agent.llm;

import com.xingtu.agent.config.AppProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 降级链：主模型优先，其后是配置的兜底链，最后永远以 mock 兜底（避免全链路不可用）。
 */
@Component
public class FallbackChain {

    private final AppProperties props;

    public FallbackChain(AppProperties props) {
        this.props = props;
    }

    public boolean mockMode() {
        return props.getLlm().isMock() || "mock".equalsIgnoreCase(props.getLlm().getPrimary());
    }

    public String primary() {
        return mockMode() ? "mock" : props.getLlm().getPrimary();
    }

    /** 有序候选名：primary + fallback（去重，保留 mock 兜底）。 */
    public List<String> names() {
        if (mockMode()) {
            return List.of("mock");
        }
        Set<String> names = new LinkedHashSet<>();
        addIfKnown(names, props.getLlm().getPrimary());
        List<String> fallbacks = props.getLlm().getFallbackChain();
        if (fallbacks != null) {
            for (String name : fallbacks) {
                addIfKnown(names, name);
            }
        }
        if (!names.contains("mock")) {
            names.add("mock");
        }
        return new ArrayList<>(names);
    }

    public String primaryModel() {
        if (mockMode()) {
            return "mock-chat";
        }
        AppProperties.Provider provider = props.getLlm().getProviders().get(props.getLlm().getPrimary());
        return provider == null ? "unknown" : provider.getModel();
    }

    public List<String> fallbackModels() {
        List<String> models = new ArrayList<>();
        boolean first = true;
        for (String name : names()) {
            if (first) {
                first = false;
                continue;
            }
            AppProperties.Provider provider = props.getLlm().getProviders().get(name);
            models.add(provider == null ? name : provider.getModel());
        }
        return models;
    }

    private void addIfKnown(Set<String> names, String name) {
        if (name == null || name.isBlank()) {
            return;
        }
        String trimmed = name.trim();
        if ("mock".equalsIgnoreCase(trimmed) || props.getLlm().getProviders().containsKey(trimmed)) {
            names.add(trimmed);
        }
    }
}
