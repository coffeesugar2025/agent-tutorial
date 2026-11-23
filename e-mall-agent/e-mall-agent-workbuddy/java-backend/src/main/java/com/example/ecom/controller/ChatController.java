package com.example.ecom.controller;

import com.example.ecom.domain.ChatRequest;
import com.example.ecom.domain.ChatResponse;
import com.example.ecom.domain.User;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.security.RbacGuard;
import com.example.ecom.service.ChatService;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.Map;
import java.util.concurrent.Executor;

@RestController
@RequestMapping("/api/chat")
public class ChatController {

    private final ChatService chatService;
    private final RbacGuard rbac;
    private final Executor sseExecutor;

    public ChatController(ChatService chatService, RbacGuard rbac,
                          @Qualifier("sseExecutor") Executor sseExecutor) {
        this.chatService = chatService;
        this.rbac = rbac;
        this.sseExecutor = sseExecutor;
    }

    /** 同步对话：POST /api/chat */
    @PostMapping
    public ChatResponse chat(@RequestBody ChatRequest request) {
        User user = TraceContext.user();
        rbac.require(user, "chat:use");
        return chatService.chat(request.message(), request.threadId(), user);
    }

    /** 契约中的 SSE：GET /api/chat/stream?message=... */
    @GetMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamGet(@RequestParam Map<String, String> params) {
        String message = params.getOrDefault("message", "");
        String threadId = params.getOrDefault("threadId", params.getOrDefault("thread_id", "default"));
        return emit(message, threadId);
    }

    /** 现有前端使用 POST /api/chat/stream + thread_id */
    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamPost(@RequestBody ChatRequest request) {
        return emit(request.message(), request.threadId());
    }

    private SseEmitter emit(String message, String threadId) {
        User user = TraceContext.user();
        rbac.require(user, "chat:use");
        SseEmitter emitter = new SseEmitter(120_000L);
        sseExecutor.execute(() -> {
            TraceContext.newTrace();
            TraceContext.setUser(user);
            try {
                chatService.stream(message, threadId, user, event -> {
                    try {
                        emitter.send(event);
                    } catch (Exception e) {
                        throw new IllegalStateException("SSE 推送失败", e);
                    }
                });
                emitter.complete();
            } catch (Exception e) {
                try {
                    emitter.send(Map.of("event", "error", "data", String.valueOf(e.getMessage())));
                } catch (Exception ignored) {
                    // ignore
                }
                emitter.completeWithError(e);
            } finally {
                TraceContext.clear();
            }
        });
        return emitter;
    }
}
