package com.example.ecom.agent;

import dev.langchain4j.model.chat.ChatModel;
import com.example.ecom.observability.Metrics;
import com.example.ecom.reliability.RetryHelper;
import dev.langchain4j.data.message.ChatMessage;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Locale;

/**
 * Supervisor：把用户输入路由到 product / order / service 三个 specialist。
 * 关键词规则优先（离线可用），未命中时用 LLM 分类并做兜底。
 */
@Component
public class Supervisor {

    private final ChatModel chatModel;
    private final Specialists specialists;
    private final RetryHelper retry;
    private final Metrics metrics;

    public Supervisor(ChatModel chatModel, Specialists specialists, RetryHelper retry, Metrics metrics) {
        this.chatModel = chatModel;
        this.specialists = specialists;
        this.retry = retry;
        this.metrics = metrics;
    }

    public Specialists.Kind route(String userInput) {
        String text = userInput == null ? "" : userInput.toLowerCase(Locale.ROOT);
        if (text.matches(".*(订单|退款|下单|物流状态|发货|签收|order|refund).*")) {
            return Specialists.Kind.ORDER;
        }
        if (text.matches(".*(商品|价格|库存|耳机|键盘|电脑|围巾|咖啡|product|stock|price).*")) {
            return Specialists.Kind.PRODUCT;
        }
        if (text.matches(".*(退货|政策|售后|质保|支付|发票|客服|service|policy).*")) {
            return Specialists.Kind.SERVICE;
        }
        try {
            String answer = retry.retry(() -> chatModel.chat(
                    "只回答 product、order 或 service 之一，不要解释。用户问题：" + userInput), 1, 0L);
            if (answer != null) {
                String a = answer.toLowerCase(Locale.ROOT);
                if (a.contains("product")) return Specialists.Kind.PRODUCT;
                if (a.contains("order")) return Specialists.Kind.ORDER;
            }
        } catch (RuntimeException ignored) {
            metrics.increment("supervisor.llm_route_failed");
        }
        return Specialists.Kind.SERVICE;
    }

    public ReActRunner.Result dispatch(Specialists.Kind kind, List<ChatMessage> messages) {
        metrics.increment("supervisor.route." + kind.name().toLowerCase(Locale.ROOT));
        return specialists.run(kind, messages);
    }
}
