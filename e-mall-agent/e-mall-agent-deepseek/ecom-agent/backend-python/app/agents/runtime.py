"""Agent 运行时：把路由、记忆、工具、流式输出、终止与审批串成一条可观测的链路。

事件生产采用 **生产者/消费者 + 队列** 模式：
模型流式回调（``on_delta``）与工具执行都在同一个协程里，通过 ``asyncio.Queue``
把 :class:`AgentEvent` 吐给外层的 async generator。这样可以避免"回调里不能 yield"的限制，
也让客户端断开时的取消语义清晰（外层 generator 关闭 → 取消任务）。

终止条件见 :mod:`app.agents.termination`，本模块只负责在执行点收集输入。
"""

# ═══════ 文件级能力标注 ═══════
# [CAP-03] 运行时循环  |  [CAP-04] 规划与反思  |  [CAP-06] 上下文工程
# 职责：Agent 运行时：把路由、记忆、工具、流式输出、终止与审批串成一条可观测的链路
# 能力编号与规范见 docs/11-代码能力标注规范.md
# ══════════════════════════════════

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents import prompts, supervisor
from app.agents.state import (
    AGENT_SUPERVISOR,
    FINISH_APPROVAL,
    FINISH_ERROR,
    FINISH_STOP,
    AgentEvent,
    AgentState,
    ToolCallRecord,
)
from app.agents.termination import (
    TerminationInput,
    detect_repeated_tool,
    detect_stall,
    evaluate,
    fallback_answer,
)
from app.common.ids import new_trace_id
from app.config import settings
from app.infra.db import session_scope
from app.infra.models import ChatMessage
from app.memory import longterm, profile
from app.memory import session as session_memory
from app.obs.metrics import (
    record_agent_step,
    record_cost,
    record_termination,
    record_tokens,
)
from app.obs.trace import SPAN_AGENT, SPAN_GUARDRAIL, TraceRecorder
from app.llm.fallback import LLMClient
from app.llm.router import TaskClass
from app.security.injection import inspect_user_input, wrap_untrusted

logger = logging.getLogger(__name__)

_SENTINEL = object()


# ──────── [CAP-11] 生态协议 / 执行环境 ────────
#   本处：Skill 渐进式披露（L1 常驻 / L2 按需）
#   域约束：对外暴露默认只读，写工具必须走审批；缺依赖时降级为纯 JSON 描述
def _skill_context(question: str) -> str:
    """渐进式披露 Skill：L1 元数据常驻，L2 正文只在触发词命中时加载。

    这样既能"知道有哪些能力"，又不会把全部 Skill 正文塞进每一次上下文
    （正文会随技能数量线性膨胀，是上下文预算的隐形杀手）。
    """
    try:
        from app.skills.loader import list_skills, load_skill_prompt

        index_block = load_skill_prompt(None, include_body=False, max_chars=1200)
        matched: list[str] = []
        for item in list_skills():
            triggers = item.get("triggers") or item.get("keywords") or []
            if isinstance(triggers, str):
                triggers = [triggers]
            if any(str(t) and str(t) in question for t in triggers if t):
                name = str(item.get("name") or "")
                if name:
                    matched.append(name)
        body_block = (
            load_skill_prompt(matched, include_body=True, max_chars=2000) if matched else ""
        )
        return "\n\n".join(part for part in (index_block, body_block) if part)
    except Exception as exc:  # noqa: BLE001 - Skill 不可用不能影响对话
        logger.debug("Skill 加载失败: %s", exc)
        return ""

# 拒绝话术：命中高危注入时使用
_REFUSAL = (
    "抱歉，这个请求看起来试图改变我的工作规则，我不能照做。"
    "如果你有商品、订单或售后方面的问题，我很乐意帮忙。"
)


class AgentRuntime:
    """单次提问的完整执行器。"""

    def __init__(self, client: LLMClient | None = None) -> None:
        self.client = client or LLMClient()

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------
    # ──────── [CAP-03] 运行时循环 ────────
    #   本处：对外入口：队列解耦流式事件
    #   域约束：判定顺序固定为 超时→步数→预算→循环→无进展，同时命中也必须稳定返回同一个原因
    async def run(
        self,
        *,
        user_id: int,
        session_id: int,
        question: str,
        trace_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """执行一次提问，逐条产出 SSE 事件。"""
        trace = trace_id or new_trace_id()
        queue: asyncio.Queue[Any] = asyncio.Queue()

        async def emit(name: str, data: dict[str, Any]) -> None:
            await queue.put(AgentEvent(name=name, data=data))

        async def drive() -> None:
            try:
                await self._drive(emit, user_id, session_id, question, trace)
            except asyncio.CancelledError:  # pragma: no cover - 客户端断开
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Agent 运行异常 trace=%s", trace)
                await emit("error", {"code": 50000, "message": f"服务内部错误：{type(exc).__name__}"})
            finally:
                await queue.put(_SENTINEL)

        task = asyncio.create_task(drive())
        try:
            while True:
                item = await queue.get()
                if item is _SENTINEL:
                    break
                yield item  # type: ignore[misc]
        finally:
            if not task.done():
                task.cancel()

    # ------------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------------
    # ──────── [CAP-03] 运行时循环 ────────
    #   本处：单次提问主流程
    #   域约束：判定顺序固定为 超时→步数→预算→循环→无进展，同时命中也必须稳定返回同一个原因
    async def _drive(
        self,
        emit: Any,
        user_id: int,
        session_id: int,
        question: str,
        trace_id: str,
    ) -> None:
        recorder = TraceRecorder(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            question=question,
        )
        recorder.start()

        # 先落占位消息，让 meta 事件能带上真实 messageId
        message_id = session_memory.append_message(
            session_id, "user", question, trace_id=trace_id
        )
        assistant_id = session_memory.append_message(
            session_id, "assistant", "", agent_type=AGENT_SUPERVISOR, trace_id=trace_id
        )
        await emit("meta", {"traceId": trace_id, "messageId": assistant_id, "sessionId": session_id})

        state = AgentState(
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            question=question,
        )
        status = "SUCCESS"

        try:
            # 1) 输入防护
            verdict = await self._guard(question, recorder)
            if verdict is not None:
                state.finish_reason = FINISH_STOP
                await emit("delta", {"text": _REFUSAL})
                state.answer_parts.append(_REFUSAL)
                status = "BLOCKED"
                return

            # 2) 路由
            history = session_memory.history_dicts(session_id, limit=6)
            agent_type, reason = await supervisor.route(question, history, self.client)
            state.agent_type = agent_type
            state.route_reason = reason
            await emit("agent", {"agentType": agent_type, "reason": reason})

            # 3) 组装上下文
            messages = await self._build_messages(state, user_id, session_id, agent_type)
            tools = self._binding_tools(agent_type)

            # 4) 主循环
            finish_reason = await self._loop(emit, state, messages, tools, recorder)
            state.finish_reason = finish_reason

            if finish_reason == FINISH_APPROVAL:
                status = "INTERRUPTED"
                return

            # 5) 兜底话术（非正常终止时避免空白）
            if finish_reason != FINISH_STOP:
                status = "FAILED" if finish_reason == FINISH_ERROR else "SUCCESS"
                if not state.answer.strip():
                    text = fallback_answer(finish_reason)
                    state.answer_parts.append(text)
                    await emit("delta", {"text": text})
        except Exception:  # noqa: BLE001 - 标记错误态后继续抛出，由外层发 error 事件
            state.finish_reason = FINISH_ERROR
            status = "FAILED"
            raise
        finally:
            await self._finalize(state, assistant_id, status, recorder, emit, message_id)

    # ------------------------------------------------------------------
    # 各阶段
    # ------------------------------------------------------------------
    # ──────── [CAP-15] 安全与合规 ────────
    #   本处：输入注入检测（高危直接拒绝）
    #   域约束：外部内容一律视为数据而非指令；PII 在统一出口脱敏，而非打印后再处理
    async def _guard(self, question: str, recorder: TraceRecorder) -> Any:
        """输入注入检测；命中高危返回 verdict，否则返回 None。"""
        try:
            verdict = inspect_user_input(question)
        except Exception as exc:  # noqa: BLE001 - 防护失败不阻断主流程
            logger.warning("注入检测失败，放行: %s", exc)
            return None

        risk = str(getattr(verdict, "risk", "SAFE")).upper()
        blocked = bool(getattr(verdict, "blocked", risk == "BLOCK"))
        recorder.record_span(
            name="guardrail.injection",
            span_type=SPAN_GUARDRAIL,
            inputs={"length": len(question)},
            output={"risk": risk, "matches": getattr(verdict, "matches", [])},
            status="OK",
        )
        return verdict if blocked else None

    # ──────── [CAP-06] 上下文工程 ────────
    #   本处：system+画像+记忆+历史+提问
    #   域约束：稳定内容在前、易变在后；画像≤200 字、记忆 top5、Skill 正文按触发词加载
    async def _build_messages(
        self, state: AgentState, user_id: int, session_id: int, agent_type: str
    ) -> list[Any]:
        """system(规则+画像+长期记忆) + 历史 + 本轮问题。"""
        extra_parts: list[str] = []
        try:
            snippet = profile.profile_snippet(user_id)
            if snippet:
                extra_parts.append(snippet)
        except Exception as exc:  # noqa: BLE001
            logger.warning("画像注入失败: %s", exc)

        try:
            memories = longterm.recall(user_id, state.question, top_k=5)
            if memories:
                extra_parts.append(
                    "【长期记忆（供参考，可能过时）】\n" + "\n".join(f"- {m}" for m in memories)
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("长期记忆召回失败: %s", exc)

        skill_block = _skill_context(state.question)
        if skill_block:
            extra_parts.append(skill_block)

        system_text = prompts.system_prompt(agent_type, "\n\n".join(extra_parts) or None)

        history, summary = session_memory.load_for_llm(session_id)
        # 本次提问已落库，装历史时要剔除末尾这条，避免重复
        if history and getattr(history[-1], "content", None) == state.question:
            history = history[:-1]

        messages: list[Any] = [SystemMessage(content=system_text)]
        if summary:
            messages.append(SystemMessage(content=f"【会话摘要】{summary}"))
        messages.extend(history)
        messages.append(HumanMessage(content=state.question))
        return messages

    @staticmethod
    def _binding_tools(agent_type: str) -> list[dict[str, Any]]:
        from app.tools.registry import openai_tools_for

        try:
            return openai_tools_for(agent_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("绑定工具失败 agent=%s err=%s", agent_type, exc)
            return []

    # ──────── [CAP-03] 运行时循环 ────────
    #   本处：终止判定 + 工具执行 + 最终答案
    #   域约束：判定顺序固定为 超时→步数→预算→循环→无进展，同时命中也必须稳定返回同一个原因
    async def _loop(
        self,
        emit: Any,
        state: AgentState,
        messages: list[Any],
        tools: list[dict[str, Any]],
        recorder: TraceRecorder,
    ) -> str:
        """Agent 主循环，返回终止原因。"""
        while True:
            reason = evaluate(
                TerminationInput(
                    step=state.step,
                    tokens=state.total_tokens,
                    elapsed_seconds=state.elapsed_seconds,
                    max_steps=settings.max_steps,
                    max_tokens=settings.max_token_budget,
                    timeout_seconds=settings.task_timeout_seconds,
                    repeated_tool=detect_repeated_tool(state.tool_signatures),
                    stalled=detect_stall(state.progress_marks),
                )
            )
            if reason is not None:
                record_termination(reason)
                return reason

            state.step += 1
            delta_buf: list[str] = []

            async def on_delta(piece: str) -> None:
                delta_buf.append(piece)
                await emit("delta", {"text": piece})

            result = await self.client.astream(
                messages,
                task=TaskClass.CHAT,
                tools=tools or None,
                on_delta=on_delta,
            )
            state.model = result.model or state.model
            state.prompt_tokens += result.usage.prompt_tokens
            state.completion_tokens += result.usage.completion_tokens
            state.cost_cents += result.cost_cents
            record_agent_step(state.agent_type, result.latency_ms / 1000.0)
            record_tokens(result.provider, result.model, result.usage.prompt_tokens, result.usage.completion_tokens)
            record_cost(result.provider, result.model, result.cost_cents)

            recorder.record_span(
                name=f"{state.agent_type.lower()}.llm",
                span_type="LLM",
                inputs={"step": state.step, "messages": len(messages)},
                output={"model": result.model, "toolCalls": len(result.tool_calls)},
                latency_ms=result.latency_ms,
                status="OK",
            )

            if result.tool_calls:
                messages.append(
                    AIMessage(content=result.text or "", tool_calls=result.tool_calls)
                )
                approval = await self._run_tools(emit, state, messages, result.tool_calls, recorder)
                if approval is not None:
                    state.approval_id = int(approval["id"])
                    await emit(
                        "approval",
                        {
                            "approvalId": approval["id"],
                            "title": approval["title"],
                            "detail": approval["detail"],
                            "risk": approval["risk"],
                            "expiresAt": approval["expiresAt"],
                        },
                    )
                    return FINISH_APPROVAL
                continue

            # 无工具调用 → 最终答案
            answer = "".join(delta_buf) or result.text
            state.answer_parts = [answer]
            state.add_progress({"answer": answer[:200], "step": state.step})
            return FINISH_STOP

    # ──────── [CAP-05] 工具治理 ────────
    #   本处：批量执行 + 风险拦截
    #   域约束：READ 可重试、WRITE 幂等、IRREVERSIBLE 必须走审批；新增工具只注册不改管线
    async def _run_tools(
        self,
        emit: Any,
        state: AgentState,
        messages: list[Any],
        tool_calls: list[dict[str, Any]],
        recorder: TraceRecorder,
    ) -> dict[str, Any] | None:
        """执行本轮所有工具调用；若触发审批则返回审批任务。"""
        from app.hitl import approval as hitl
        from app.tools.base import ApprovalRequired, Risk, ToolContext, executor
        from app.tools.registry import get_spec

        ctx = ToolContext(
            user_id=state.user_id,
            session_id=state.session_id,
            trace_id=state.trace_id,
            agent_type=state.agent_type,
            recorder=recorder,
        )

        for raw in tool_calls:
            name = str(raw.get("name") or "")
            args = dict(raw.get("args") or {})
            call_id = str(raw.get("id") or f"call_{state.step}_{len(state.tool_calls)}")

            try:
                spec = get_spec(name)
                risk = spec.risk.value
            except KeyError:
                risk = Risk.READ.value
                await emit("tool_call", {"callId": call_id, "name": name, "args": args, "risk": risk})
                await emit(
                    "tool_result",
                    {"callId": call_id, "name": name, "ok": False, "summary": "工具不存在", "latencyMs": 0},
                )
                messages.append(
                    ToolMessage(content="工具不存在", tool_call_id=call_id, name=name or "unknown")
                )
                continue

            state.add_signature(name, args)
            await emit("tool_call", {"callId": call_id, "name": name, "args": args, "risk": risk})

            try:
                outcome = await executor.execute(spec, args, ctx, call_id=call_id)
            except ApprovalRequired as exc:
                task = hitl.approval_from_exception(
                    exc, session_id=state.session_id, user_id=state.user_id, trace_id=state.trace_id
                )
                state.add_progress({"approval": task["id"], "step": state.step})
                return task

            record = ToolCallRecord(
                call_id=call_id,
                name=name,
                args=args,
                ok=outcome.ok,
                summary=outcome.summary[:300],
                latency_ms=outcome.latency_ms,
                risk=risk,
            )
            state.tool_calls.append(record)
            await emit("tool_result", outcome.to_event())

            await self._collect_citations(emit, state, name, outcome.data)
            state.add_progress({"tool": name, "ok": outcome.ok, "summary": outcome.summary[:120]})

            content = wrap_untrusted(outcome.to_content(), source=f"tool:{name}", kind="tool")
            messages.append(ToolMessage(content=content, tool_call_id=call_id, name=name))

        return None
    # ──────── [CAP-12] 检索增强 RAG ────────
    #   本处：引用抽取（docId/chunkId/score）
    #   域约束：任一环节失败必须降级并标记 degraded，不允许静默返回空结果

    @staticmethod
    async def _collect_citations(
        emit: Any, state: AgentState, tool_name: str, data: dict[str, Any]
    ) -> None:
        """从检索类工具结果里提取引用，去重后缓存到 state 并推送 SSE。"""
        if tool_name not in ("search_knowledge",) or not isinstance(data, dict):
            return
        items = data.get("items") or data.get("chunks") or []
        if not isinstance(items, list):
            return
        seen = {(c.get("chunkId"), c.get("docId")) for c in state.citations}
        for item in items[:5]:
            if not isinstance(item, dict):
                continue
            citation = {
                "docId": item.get("docId") or item.get("documentId"),
                "chunkId": item.get("chunkId"),
                "title": item.get("title") or "",
                "snippet": str(item.get("content") or item.get("snippet") or "")[:200],
                "score": float(item.get("score") or 0.0),
            }
            key = (citation["chunkId"], citation["docId"])
            if key in seen or citation["chunkId"] is None:
                continue
            seen.add(key)
            state.citations.append(citation)
            await emit("citation", citation)

    # ------------------------------------------------------------------
    # 收尾
    # ------------------------------------------------------------------
    # ──────── [CAP-16] 可观测与调试 ────────
    #   本处：回写消息/trace/成本/记忆抽取
    #   域约束：span 必须 try/finally 收口；不打印完整 prompt，只记 hash 与长度
    async def _finalize(
        self,
        state: AgentState,
        assistant_id: int,
        status: str,
        recorder: TraceRecorder,
        emit: Any,
        user_message_id: int,
    ) -> None:
        answer = state.answer
        try:
            with session_scope() as db:
                row = db.get(ChatMessage, assistant_id)
                if row is not None:
                    row.content = answer
                    row.agent_type = state.agent_type
                    row.tool_calls = [call.to_dict() for call in state.tool_calls] or None
                    row.citations = state.citations or None
                    row.token_in = state.prompt_tokens
                    row.token_out = state.completion_tokens
                    row.cost_cents = state.cost_cents
        except Exception as exc:  # noqa: BLE001
            logger.warning("回写助手消息失败 id=%s err=%s", assistant_id, exc)

        recorder.finish(
            status=status,
            answer=answer,
            step_count=state.step,
            cost_cents=state.cost_cents,
            agent_type=state.agent_type,
        )

        # 抽取长期记忆（规则式，零成本）
        try:
            if status == "SUCCESS":
                longterm.persist_candidates(state.user_id, state.question, state.session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("长期记忆抽取失败: %s", exc)

        # 会话摘要触发
        try:
            session_memory.maybe_trigger_summary(
                state.session_id, session_memory.count_messages(state.session_id)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("摘要触发失败: %s", exc)

        await emit(
            "usage",
            {
                "promptTokens": state.prompt_tokens,
                "completionTokens": state.completion_tokens,
                "costCents": state.cost_cents,
                "model": state.model or "unknown",
            },
        )
        finish_reason = state.finish_reason or FINISH_STOP
        if finish_reason != FINISH_ERROR:
            await emit(
                "done",
                {"messageId": assistant_id, "finishReason": finish_reason, "stepCount": state.step},
            )


__all__ = ["AgentRuntime"]
