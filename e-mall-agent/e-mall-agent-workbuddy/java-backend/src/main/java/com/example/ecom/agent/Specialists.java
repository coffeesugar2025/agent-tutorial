package com.example.ecom.agent;

import dev.langchain4j.data.message.ChatMessage;
import dev.langchain4j.data.message.SystemMessage;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * Multi-Agent 的三个 specialist：product / order / service。
 * 每个 specialist 使用不同的系统提示与工具策略，共享同一个 ReActRunner。
 * 声明式替换点：可将每个 specialist 改写为 AiServices.builder(...).systemMessage(...).tools(...) 的 @AiService。
 */
@Component
public class Specialists {

    public enum Kind { PRODUCT, ORDER, SERVICE }

    private final ReActRunner runner;

    public Specialists(ReActRunner runner) {
        this.runner = runner;
    }

    public String systemPrompt(Kind kind) {
        return switch (kind) {
            case PRODUCT -> "你是商品专家。只基于商品搜索与库存工具返回的事实回答，"
                    + "回答中给出商品名、价格、库存；不确定时明确说明。";
            case ORDER -> "你是订单专家。负责查询订单、解释履约状态（created→paid→shipped→delivered）与退款流程；"
                    + "大额退款必须走审批流程，不得承诺直接退款。";
            case SERVICE -> "你是电商客服助手。基于知识库引用回答退货政策、物流、支付与售后问题，"
                    + "回答中标注引用编号；必要时调用工具核实。";
        };
    }

    public ReActRunner.Result run(Kind kind, List<ChatMessage> messages) {
        List<ChatMessage> copy = new ArrayList<>(messages);
        SystemMessage specialist = SystemMessage.from(systemPrompt(kind));
        if (!copy.isEmpty() && copy.get(0) instanceof SystemMessage) {
            copy.set(0, specialist);
        } else {
            copy.add(0, specialist);
        }
        return runner.run(copy, true);
    }
}
