package com.example.order.outbox;

/**
 * 发送端抽象。实现必须「同步确认投递成功」才算成功：
 * 抛异常 / 返回前未确认，OutboxDispatcher 会保留 PENDING 并退避重试，
 * 否则消息会在「已标记 SENT」但 broker 没收到的情况下永久丢失。
 */
public interface MessageSender {
    void send(OutboxMessage message) throws Exception;
}
