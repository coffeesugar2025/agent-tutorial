"""P0/P1 生产加固层：对照《Agent 开发知识点总纲》第 5/6/7 章补齐的缺口。

  injection          间接 Prompt Injection 数据化封装（6.3）
  acl                检索层 ACL 先过滤再检索（4.7 / 5.3）
  errors             可重试错误分类（5.1）
  cache              四级缓存 + 知识更新失效（4.16 / 5.8）
  replay             完整轨迹落盘 + 确定性重放 + 时间旅行（5.6）
  cost               每成功任务成本 / 预算终止（0.5 / 5.8）
  prompt_registry    Prompt 版本 / hash / 灰度（5.7 / 9.2）
  rag_eval           分层评估 recall@k / MRR / nDCG / context precision（4.12 / 7.2）
  query_understanding 改写 / 分解 / multi-query / HyDE / 不检索判定（4.6）
  stability          pass^k / 方差 / 稳定性（7.2 / 7.4）
  tools              工具设计学注册表（2.3）
  memory_v2         记忆冲突消解 / 衰减 / 写入策略（2.6）
  hitl_v2           HITL 超时默认拒绝 / 事中打断 / 事后审核（3.6）
"""
