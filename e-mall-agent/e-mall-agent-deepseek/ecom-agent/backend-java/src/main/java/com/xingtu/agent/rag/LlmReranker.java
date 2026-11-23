package com.xingtu.agent.rag;

import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.llm.FallbackChain;
import com.xingtu.agent.llm.LlmProvider;
import com.xingtu.agent.llm.ModelRouter;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 重排：RERANK_PROVIDER=llm 且非 mock 时用模型打分，否则退化为词面覆盖度打分（确定性、零成本）。
 * 模型不可用时自动回退，不影响检索主流程。
 */
@Component
public class LlmReranker {

    private static final Logger log = LoggerFactory.getLogger(LlmReranker.class);

    public record Candidate(long chunkId, long docId, String title, String content, double baseScore) {
    }

    public record Ranked(long chunkId, long docId, String title, String content, double baseScore,
                         double rerankScore) {
    }

    private final AppProperties props;
    private final ModelRouter modelRouter;
    private final FallbackChain fallbackChain;
    private final SparseEncoder encoder;

    public LlmReranker(AppProperties props, ModelRouter modelRouter, FallbackChain fallbackChain,
                       SparseEncoder encoder) {
        this.props = props;
        this.modelRouter = modelRouter;
        this.fallbackChain = fallbackChain;
        this.encoder = encoder;
    }

    public List<Ranked> rerank(String query, List<Candidate> candidates, int topN) {
        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }
        List<Ranked> scored = new ArrayList<>();
        boolean useLlm = "llm".equalsIgnoreCase(props.getLlm().getRerankProvider())
                && !fallbackChain.mockMode();
        for (Candidate candidate : candidates) {
            double lexical = coverage(query, candidate.content());
            double score = lexical;
            if (useLlm) {
                Double llmScore = llmScore(query, candidate.content());
                if (llmScore != null) {
                    score = 0.4d * lexical + 0.6d * llmScore;
                }
            }
            scored.add(new Ranked(candidate.chunkId(), candidate.docId(), candidate.title(),
                    candidate.content(), candidate.baseScore(), round(score)));
        }
        scored.sort(Comparator.comparingDouble(Ranked::rerankScore).reversed());
        return scored.size() > topN ? new ArrayList<>(scored.subList(0, topN)) : scored;
    }

    /** 词面覆盖度：查询词在文档中的覆盖比例（0~1）。 */
    public double coverage(String query, String content) {
        Set<String> queryTerms = new LinkedHashSet<>(encoder.terms(query));
        if (queryTerms.isEmpty() || content == null || content.isEmpty()) {
            return 0d;
        }
        Set<String> docTerms = new LinkedHashSet<>(encoder.terms(content));
        int hit = 0;
        for (String term : queryTerms) {
            if (docTerms.contains(term)) {
                hit++;
            }
        }
        return round((double) hit / queryTerms.size());
    }

    private Double llmScore(String query, String content) {
        try {
            List<LlmProvider.Message> messages = new ArrayList<>();
            messages.add(LlmProvider.Message.system(
                    "你是检索相关性打分器。只输出 0 到 1 之间的小数，表示文档与问题的相关度，不要输出任何解释。"));
            messages.add(LlmProvider.Message.user("问题：" + query + "\n文档：" + abbreviate(content, 600)
                    + "\n相关度："));
            LlmProvider.Result result = modelRouter.chat(new LlmProvider.Request(messages, 0d, 16));
            return clamp(parseDouble(result.text()));
        } catch (RuntimeException e) {
            log.debug("LLM 重排失败，回退词面打分: {}", e.getMessage());
            return null;
        }
    }

    private double parseDouble(String text) {
        if (text == null) {
            return 0d;
        }
        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("([0-9]+(?:\\.[0-9]+)?)").matcher(text);
        if (matcher.find()) {
            try {
                return Double.parseDouble(matcher.group(1));
            } catch (NumberFormatException e) {
                return 0d;
            }
        }
        return 0d;
    }

    private double clamp(double value) {
        return Math.max(0d, Math.min(1d, value));
    }

    private double round(double value) {
        return Math.round(value * 10000d) / 10000d;
    }

    private String abbreviate(String text, int max) {
        if (text == null) {
            return "";
        }
        return text.length() <= max ? text : text.substring(0, max);
    }
}
