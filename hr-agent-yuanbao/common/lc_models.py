"""LangChain 模型层：ChatModel / Embeddings 的可切换实现。

设计要点：**离线演示模式也走真正的 LangChain 接口**。
TeachingChatModel 继承 BaseChatModel、实现 _generate 并支持 tool_calls，
所以 LangGraph 的 ToolNode、bind_tools、条件边、interrupt 全部是真实执行的，
只是「模型这一格」换成了确定性应答。装了 Ollama 后一行配置切回 ChatOllama。
"""
from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from . import config
from .context import _mock_embedding


# ---------------- Embeddings ----------------

class TeachingEmbeddings(Embeddings):
    """离线向量：确定性哈希投影，和前 15 章 common/context.py 完全一致。"""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [_mock_embedding(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return _mock_embedding(text)


def build_embeddings(mode: str) -> Embeddings:
    if mode == "ollama":
        from langchain_community.embeddings import OllamaEmbeddings
        return OllamaEmbeddings(base_url=config.OLLAMA_BASE_URL, model=config.OLLAMA_EMBED_MODEL)
    return TeachingEmbeddings()


# ---------------- 意图关键词（离线模型用） ----------------

def _last_human(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return str(m.content)
    return str(messages[-1].content) if messages else ""


def _system_json(messages: list[BaseMessage]) -> dict:
    """节点会把结构化上下文放进一条 SystemMessage，模型从这里读。"""
    for m in messages:
        if isinstance(m, SystemMessage) and str(m.content).startswith("HR_CTX:"):
            try:
                return json.loads(str(m.content)[7:])
            except json.JSONDecodeError:
                return {}
    return {}


def classify_intent(question: str) -> dict:
    q = question
    if "MCP" in q.upper():
        return {"intent": "mcp", "reason": "显式要求走 MCP Server", "confidence": 0.99}
    if any(w in q for w in ("入职", "办入职", "新员工", "onboarding")):
        return {"intent": "onboarding", "reason": "需要建单并走审批状态机", "confidence": 0.97}
    if any(w in q for w in ("平均", "统计", "加班多久", "多少小时", "SQL", "考勤报表")):
        return {"intent": "sql", "reason": "需要精确计算，走 Text2SQL 只读网关", "confidence": 0.95}
    if any(w in q for w in ("同一个项目", "汇报给", "同事", "图谱", "关系")):
        return {"intent": "graph", "reason": "需要沿关系多跳遍历，走图谱检索", "confidence": 0.94}
    if any(w in q for w in ("年假", "余额", "还剩几天", "剩余假期", "查一下我的")):
        return {"intent": "tool", "reason": "个人实时数据，必须查 HCM 工具", "confidence": 0.98}
    if any(w in q for w in ("婚假", "病假", "产假", "报销", "试用期", "辞退", "转正", "晋升",
                            "绩效", "补贴", "制度", "规定", "流程", "手册", "SOP", "条款")):
        return {"intent": "rag", "reason": "制度类问题，需要带版本与引用", "confidence": 0.96}
    return {"intent": "chat", "reason": "通用问答，无需外部知识", "confidence": 0.7}


SQL_MOCK = (
    "SELECT e.dept, ROUND(AVG(a.overtime), 2) AS avg_overtime "
    "FROM attendance a JOIN employees e ON a.emp_id = e.emp_id "
    "WHERE a.month = '2026-10' AND e.dept = '产品部' GROUP BY e.dept"
)


class TeachingChatModel(BaseChatModel):
    """离线教学模型：实现 LangChain BaseChatModel 契约，按 role 返回确定性应答。

    role 决定它「扮演哪个节点的模型」，内容一律从 messages 里读，
    所以同一份 graph 结构可以复用于任何 scenario，也便于 interrupt 恢复后重放。
    """

    role: str = "compose"
    available_tools: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "teaching-mock"

    def bind_tools(self, tools: list[Any], **kwargs: Any) -> "TeachingChatModel":
        names = []
        for t in tools:
            names.append(getattr(t, "name", None) or getattr(t, "__name__", "unknown"))
        return TeachingChatModel(role="tools", available_tools=names)

    def _generate(self, messages: list[BaseMessage], stop: list[str] | None = None,
                  run_manager: Any = None, **kwargs: Any) -> ChatResult:
        text = self._respond(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))]) \
            if isinstance(text, str) else \
            ChatResult(generations=[ChatGeneration(message=text)])

    # ---------- 各 role 的确定性应答 ----------
    def _respond(self, messages: list[BaseMessage]) -> str | AIMessage:
        q = _last_human(messages)
        ctx = _system_json(messages)

        # 各章把「教学应答」放进 SystemMessage 的 HR_CTX，模型链路仍走 BaseChatModel：
        # LCEL、bind_tools、ToolNode、回调、interrupt 全部真实执行。
        # 真实 Ollama 模式返回 ChatOllama，不会走到这里。
        if "mock_tool" in ctx:
            spec = ctx["mock_tool"]
            return AIMessage(content="", tool_calls=[{
                "name": spec.get("name", "get_leave_balance"),
                "args": spec.get("args", {}), "id": "call_1", "type": "tool_call"}])
        if "mock_response" in ctx:
            v = ctx["mock_response"]
            return json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else str(v)

        if self.role == "router":
            intent = classify_intent(q)
            return json.dumps(intent, ensure_ascii=False)

        if self.role == "plan":
            return json.dumps({
                "goal": f"完成 HR 任务：{q}",
                "steps": [
                    {"id": 1, "title": "识别意图并装配上下文", "node": "guard_memory → router → context_build"},
                    {"id": 2, "title": "核对入职材料", "node": "prepare_onboarding"},
                    {"id": 3, "title": "主管审批（强制人工）", "node": "human_approval"},
                    {"id": 4, "title": "HR 复核与 IT 开账号", "node": "post_approval"},
                    {"id": 5, "title": "生成带引用的回答", "node": "compose"},
                ],
                "success_criteria": "生成 case_id、材料齐全、审批节点挂起、全程可审计",
            }, ensure_ascii=False)

        if self.role == "summarize":
            return "历史要点：用户已确认身份 E1001；此前讨论过假期与报销口径；未提交任何单据。"

        if self.role == "tools":
            # ReAct 循环：看到 ToolMessage 说明工具已执行，交回 compose
            if any(isinstance(m, ToolMessage) for m in messages):
                return "工具结果已回灌，信息充分，交给 compose 节点生成最终回答。"
            name, args = self._choose_tool(q, ctx)
            return AIMessage(content="", tool_calls=[
                {"name": name, "args": args, "id": "call_1", "type": "tool_call"}
            ])

        if self.role == "compose":
            return self._compose(q, ctx)

        return "（离线演示模型：未识别的 role）"

    def _choose_tool(self, q: str, ctx: dict) -> tuple[str, dict]:
        intent = ctx.get("intent") or classify_intent(q)["intent"]
        emp = ctx.get("emp_id", "E1001")
        if intent == "sql":
            return "readonly_sql", {"sql": SQL_MOCK}
        if intent == "graph":
            entity = "张三" if "张三" in q else "李四"
            return "org_graph_query", {"entity": entity, "relation": "参与项目"}
        if intent == "mcp" and "mcp_hr_query" in self.available_tools:
            return "mcp_hr_query", {"emp_id": emp}
        if "mcp_hr_query" in self.available_tools and "MCP" in q.upper():
            return "mcp_hr_query", {"emp_id": emp}
        return "get_leave_balance", {"emp_id": emp}

    def _compose(self, q: str, ctx: dict) -> str:
        intent = ctx.get("intent", "chat")
        docs = ctx.get("documents", [])
        tools = ctx.get("tool_results", [])
        case = ctx.get("case_id")
        if intent == "onboarding":
            status = ctx.get("status", "WAIT_MANAGER_APPROVE")
            if status == "DONE":
                return (f"入职单 {case} 已完成：材料核对 → 主管审批 → HR 复核 → IT 开账号全部走完，"
                        f"ITSM 工单已记录。全流程由 LangGraph 状态图驱动，人工审批节点通过 interrupt 恢复。")
            return (f"入职单 {case} 已创建，材料核对完成，流程当前停在「主管审批」。"
                    f"按《招聘与入职 SOP》1.3，Agent 不得代批，请在控制台点击通过或驳回。")
        if docs:
            top = docs[0]
            cite = top.get("citation_id", 1)
            title = top.get("title", "HR 制度")
            section = top.get("section", "")
            ver = top.get("version", "V2.3")
            snippet = top.get("text", "")[:170]
            extra = f" 另检索到 {len(docs)-1} 条相关片段。" if len(docs) > 1 else ""
            return (f"依据《{title}》{section}（{ver}）：{snippet}[{cite}]。{extra}"
                    f"回答仅基于已标注 active 的检索片段，未提供的信息不作推断。")
        if tools:
            last = tools[-1] if isinstance(tools[-1], dict) else {"raw": tools[-1]}
            data = last.get("data", last)
            if intent == "sql" and isinstance(data, dict) and data.get("rows"):
                r = data["rows"][0]
                return (f"产品部 2026-10 平均加班 {r.get('avg_overtime')} 小时，"
                        f"由 Text2SQL 只读网关精确计算，SQL 已通过白名单校验。")
            if intent == "graph" and isinstance(data, dict):
                triples = data.get("relation_hits", [])
                names = sorted({t[0] for t in triples if isinstance(t, (list, tuple)) and len(t) >= 1})
                return (f"图谱 2 跳子图检索到 {len(data.get('triples', []))} 条三元组；"
                        f"关系「{data.get('entity')}」命中 {len(triples)} 条，涉及 {', '.join(names[:5]) or '无'}。"
                        f"实体均可溯源到子图，未使用子图之外的信息。")
            if isinstance(data, dict) and "leave_balance" in data:
                return (f"{data.get('name','员工')} 年假余额 {data['leave_balance']} 天，"
                        f"数据来自 {data.get('source','HCM')}，截至 {data.get('as_of','')}。")
            if last.get("degraded"):
                return (f"主链路失败已降级到缓存：{json.dumps(data, ensure_ascii=False)[:150]}。"
                        f"注意该结果带时效性标注，不是实时数据。")
            return f"已通过工具链获取实时数据并校验：{json.dumps(data, ensure_ascii=False)[:220]}。"
        return f"关于「{q}」：这是通用问答，未检索到需要引用的制度或需要调用的业务工具。"


def build_chat_model(mode: str, role: str = "compose"):
    """真实模式用 ChatOllama；离线模式用 TeachingChatModel。两者都是 LangChain ChatModel。"""
    if mode == "ollama":
        from langchain_ollama import ChatOllama
        kwargs: dict[str, Any] = {
            "base_url": config.OLLAMA_BASE_URL,
            "model": config.OLLAMA_MODEL,
            "temperature": 0.0,
        }
        if role in ("router", "plan"):
            kwargs["format"] = "json"     # 让本地模型直接吐 JSON，配合 PydanticOutputParser
        return ChatOllama(**kwargs)
    return TeachingChatModel(role=role)
