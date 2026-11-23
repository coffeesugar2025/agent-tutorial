package com.xingtu.agent.llm;

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.config.AppProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 模型路由：主模型 -> 兜底链 -> mock，配合熔断器做快速失败。
 * 全部失败时抛 50300（上层转兜底话术 + 转人工）。
 */
@Component
public class ModelRouter {

    private static final Logger log = LoggerFactory.getLogger(ModelRouter.class);

    private final AppProperties props;
    private final ChatModelFactory factory;
    private final CircuitBreaker breaker;
    private final CostCalculator costCalculator;
    private final LlmCallRecorder recorder;

    public ModelRouter(AppProperties props, ChatModelFactory factory, CircuitBreaker breaker,
                       CostCalculator costCalculator, LlmCallRecorder recorder) {
        this.props = props;
        this.factory = factory;
        this.breaker = breaker;
        this.costCalculator = costCalculator;
        this.recorder = recorder;
    }

    public LlmProvider.Result chat(List<LlmProvider.Message> messages) {
        return chat(new LlmProvider.Request(messages, props.getLlm().getTemperature(),
                props.getLlm().getMaxTokens()));
    }

    public LlmProvider.Result chat(LlmProvider.Request request) {
        int costCents = 0;
        StringBuilder failure = new StringBuilder();
        for (LlmProvider provider : factory.ordered()) {
            if (!breaker.allowRequest(provider.name())) {
                failure.append(provider.name()).append("(circuit open); ");
                continue;
            }
            long start = System.currentTimeMillis();
            try {
                LlmProvider.Result result = provider.chat(request);
                costCents = costCalculator.costCents(result.model(), result.promptTokens(),
                        result.completionTokens());
                breaker.recordSuccess(provider.name(), result.latencyMs());
                recorder.record(result.provider(), result.model(), result.promptTokens(),
                        result.completionTokens(), costCents, result.latencyMs(), "OK");
                return result;
            } catch (RuntimeException e) {
                long latency = System.currentTimeMillis() - start;
                breaker.recordFailure(provider.name());
                recorder.recordFailure(provider.name(), provider.model(), latency, e.getMessage());
                failure.append(provider.name()).append(": ").append(e.getMessage()).append("; ");
                log.warn("模型 {} 调用失败，尝试下一个兜底: {}", provider.name(), e.getMessage());
            }
        }
        throw BizException.degraded("所有模型均不可用: " + abbreviate(failure.toString()));
    }

    /** 运营面板用：各供应商健康度。 */
    public List<ModelStatus> statuses() {
        List<ModelStatus> list = new ArrayList<>();
        boolean primary = true;
        for (String name : factory.chainNames()) {
            LlmProvider provider = factory.all().get(name);
            String model = provider == null ? name : provider.model();
            boolean configured = provider != null && provider.configured();
            String circuit = breaker.state(name);
            list.add(new ModelStatus(name, model, primary ? "primary" : "fallback", configured,
                    circuit, breaker.avgLatencyMs(name), breaker.calls(name)));
            primary = false;
        }
        return list;
    }

    public record ModelStatus(String provider, String model, String role, boolean healthy, String circuit,
                              long avgLatencyMs, long calls) {
    }

    private String abbreviate(String text) {
        if (text == null) {
            return "";
        }
        return text.length() <= 300 ? text : text.substring(0, 300);
    }
}
