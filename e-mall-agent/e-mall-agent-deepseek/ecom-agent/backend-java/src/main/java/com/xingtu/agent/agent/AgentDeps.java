package com.xingtu.agent.agent;

// ═══════ 文件级能力标注 ═══════
// [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
// 职责：AgentRuntime 的依赖集合：集中声明依赖边界，便于测试时整体替换
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.config.AppProperties;
import com.xingtu.agent.hitl.ApprovalService;
import com.xingtu.agent.infra.repo.CheckpointRepository;
import com.xingtu.agent.infra.repo.MessageRepository;
import com.xingtu.agent.infra.repo.SessionRepository;
import com.xingtu.agent.llm.CostCalculator;
import com.xingtu.agent.llm.ModelRouter;
import com.xingtu.agent.memory.LongTermMemory;
import com.xingtu.agent.memory.SessionMemory;
import com.xingtu.agent.memory.UserProfileService;
import com.xingtu.agent.obs.MetricsCollector;
import com.xingtu.agent.obs.StructuredLogger;
import com.xingtu.agent.obs.Tracer;
import com.xingtu.agent.rag.ContextAssembler;
import com.xingtu.agent.rag.HybridRetriever;
import com.xingtu.agent.security.InjectionDetector;
import com.xingtu.agent.security.PiiMasker;
import com.xingtu.agent.tool.ToolRegistry;

/**
 * AgentRuntime 的依赖集合：集中声明依赖边界，便于测试时整体替换。
 */
public record AgentDeps(AppProperties props,
                        ModelRouter modelRouter,
                        CostCalculator costCalculator,
                        ToolRegistry toolRegistry,
                        AgentRegistry agentRegistry,
                        SessionMemory sessionMemory,
                        LongTermMemory longTermMemory,
                        UserProfileService userProfileService,
                        HybridRetriever retriever,
                        ContextAssembler contextAssembler,
                        Tracer tracer,
                        MetricsCollector metrics,
                        ApprovalService approvalService,
                        InterruptRegistry interrupts,
                        SessionRepository sessionRepository,
                        MessageRepository messageRepository,
                        CheckpointRepository checkpointRepository,
                        StructuredLogger structuredLogger,
                        InjectionDetector injectionDetector,
                        PiiMasker piiMasker) {
}
