package com.xingtu.agent.config;

import com.xingtu.agent.agent.AgentDeps;
import com.xingtu.agent.agent.AgentRegistry;
import com.xingtu.agent.agent.InterruptRegistry;
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
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Agent 依赖装配：把散落的组件收敛成一个 AgentDeps，AgentRuntime 只依赖这一个入口。
 */
@Configuration
public class AgentConfig {

    @Bean
    public AgentDeps agentDeps(AppProperties props,
                               ModelRouter modelRouter,
                               CostCalculator costCalculator,
                               ToolRegistry toolRegistry,
                               AgentRegistry agentRegistry,
                               SessionMemory sessionMemory,
                               LongTermMemory longTermMemory,
                               UserProfileService userProfileService,
                               HybridRetriever hybridRetriever,
                               ContextAssembler contextAssembler,
                               Tracer tracer,
                               MetricsCollector metricsCollector,
                               ApprovalService approvalService,
                               InterruptRegistry interruptRegistry,
                               SessionRepository sessionRepository,
                               MessageRepository messageRepository,
                               CheckpointRepository checkpointRepository,
                               StructuredLogger structuredLogger,
                               InjectionDetector injectionDetector,
                               PiiMasker piiMasker) {
        return new AgentDeps(props, modelRouter, costCalculator, toolRegistry, agentRegistry, sessionMemory,
                longTermMemory, userProfileService, hybridRetriever, contextAssembler, tracer,
                metricsCollector, approvalService, interruptRegistry, sessionRepository, messageRepository,
                checkpointRepository, structuredLogger, injectionDetector, piiMasker);
    }
}
