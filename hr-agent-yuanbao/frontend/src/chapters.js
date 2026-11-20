// 后端未启动时的兜底目录：能看见学习路线，但表单与运行需要 API。
// 正常情况全部由 GET /api/chapters 下发，新增章节不用改前端。
export const FALLBACK_GROUPS = [
  '入门：LCEL / 循环与工具', '决策与流程：StateGraph', '上下文与知识：Retriever',
  '协作与扩展：MCP / Multi-Agent', '生产化：护栏 / 评测 / 模型工程', '综合：LangGraph 全链路',
]

export const FALLBACK_CHAPTERS = [
  ['ch01_loop', 1, 'Agent Loop（LCEL vs StateGraph）', 0],
  ['ch02_toolcall', 2, 'Tool Calling（@tool + bind_tools + ToolNode）', 0],
  ['ch03_react_plan', 3, 'ReAct / Plan-and-Solve（LangGraph）', 1],
  ['ch04_workflow_hitl', 4, 'StateGraph / interrupt / 人工审批', 1],
  ['ch05_memory', 5, 'Memory（InMemoryStore + checkpointer）', 2],
  ['ch06_context', 6, 'Context Engineering（trim_messages）', 2],
  ['ch07_rag_basic', 7, 'RAG 基础（Document / VectorStore / LCEL）', 2],
  ['ch08_rag_advanced', 8, '混合检索 / 版本治理（BaseRetriever）', 2],
  ['ch09_graph_text2sql', 9, 'Text2SQL / 图谱 / Ontology', 2],
  ['ch10_mcp_skill', 10, 'MCP / Skill / Plugin', 3],
  ['ch11_multiagent', 11, 'Multi-Agent（LangGraph supervisor）', 3],
  ['ch12_sandbox_codemode', 12, 'Sandbox / Code Mode / checkpoint 恢复', 3],
  ['ch13_reliability', 13, '可靠性（with_retry / with_fallbacks）', 4],
  ['ch14_eval', 14, 'Trace / Metrics / 评测回归', 4],
  ['ch15_model_engineering', 15, '模型路由与结构化输出', 4],
  ['ch16_langchain_fullchain', 16, 'LangGraph 全链路综合', 5],
].map(([id, no, title, g]) => ({
  id, no, title, group: FALLBACK_GROUPS[g], brief: '启动后端后可运行本章 LangChain Demo。', fields: [],
}))
