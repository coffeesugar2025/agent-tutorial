"""Agent 工程化能力扩展包。

原项目覆盖：Agent Loop / Tool Calling / MCP / 会话记忆 / 中间件 / 流式 / 结构化输出。
本包补齐生产级能力矩阵中缺失的工程层，全部可在 AGENT_MODE=mock 下离线运行：

  planning       ReAct / Plan-and-Solve
  workflow       LangGraph StateGraph 显式状态机
  multi_agent    Supervisor + 领域专家协作
  hitl           人工审批 / interrupt-resume
  memory         长期记忆 / 用户记忆（跨 thread）
  context        Token 预算 / 上下文压缩 / 裁剪
  reliability    重试 / 超时 / 幂等 / 熔断 / 降级 / 终止条件
  harness        Sandbox / Code Mode / 长任务恢复
  observability  Trace / Metrics / 评测 / Replay
  skills         Skill / Plugin 注册表与组合
  model_eng      模型路由 / 成本延迟 / 部署策略 / 训练任务契约
  rag            文档工程 / 混合检索 / Rerank / Text2SQL / GraphRAG / 引用治理

设计原则：不破坏原有 8 个接口与 97 个回归用例；所有新能力以 /v2/* 端点暴露，
共享同一份领域数据（app.services.catalog）与同一套事实约束。
"""
