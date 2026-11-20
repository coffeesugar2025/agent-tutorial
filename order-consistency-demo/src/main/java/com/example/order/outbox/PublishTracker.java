package com.example.order.outbox;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 把 RabbitTemplate 的两个异步回调（confirm / return）合并成一个可同步等待的结果。
 *
 * <p>关键点：mandatory=true 时，broker 对不可路由消息会先发 basic.return、再发 basic.ack。
 * 只看 confirm 会误判为成功，消息其实已被丢弃。AMQP 规范保证 return 先于 confirm，
 * 所以 return 先把 future 置为失败，confirm 再 complete 时不会覆盖它。
 */
@Component
public class PublishTracker {

    private static final Logger log = LoggerFactory.getLogger(PublishTracker.class);

    private final ConcurrentHashMap<String, CompletableFuture<String>> pending =
            new ConcurrentHashMap<>();

    /** 返回 future：complete(null)=投递成功，complete(非空)=失败原因 */
    public CompletableFuture<String> register(String outboxId) {
        CompletableFuture<String> f = new CompletableFuture<>();
        CompletableFuture<String> old = pending.put(outboxId, f);
        if (old != null) {
            old.cancel(true); // 上一次投递超时后残留，作废
        }
        return f;
    }

    /** ReturnsCallback：消息不可路由 */
    public void markReturned(String outboxId, String reason) {
        CompletableFuture<String> f = pending.get(outboxId);
        if (f != null && f.complete("UNROUTABLE: " + reason)) {
            log.error("[rabbit] message returned, outboxId={}, reason={}", outboxId, reason);
        }
    }

    /** ConfirmCallback：broker 已收到(ack) 或拒收(nack) */
    public void markConfirmed(String outboxId, boolean ack, String cause) {
        CompletableFuture<String> f = pending.remove(outboxId);
        if (f == null) {
            return; // 已超时清理
        }
        // 若 return 已把 future 置为失败，这里的 complete 会返回 false，失败原因得以保留
        f.complete(ack ? null : "NACK: " + cause);
    }

    public void discard(String outboxId) {
        pending.remove(outboxId);
    }
}
