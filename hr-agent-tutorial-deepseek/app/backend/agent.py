"""Agent Loop：意图路由 → LangChain 工具调用 / 确定性工作流 → 审批中断 → 模板化回复。

2026-11 起，这个后端不再只是“手写 pipeline”，而是把 LangChain 1.x /
LangGraph 嵌入到原有业务里。集成方式是刻意分层的：

- **读走 Agent**：``leave_balance`` / ``leave_policy`` / ``candidate_search`` /
  ``candidate_query`` / ``ticket_query`` 这 5 类只读意图，会构造
  ``create_agent(model=..., tools=..., checkpointer=InMemorySaver())``。
  模型（默认 ``MockChatModel``；显式设置 ``HR_LLM_MODE`` 后走
  ``get_chat_model()``）通过 ``bind_tools`` 看到 5 个只读 ``@tool``，选择工具
  并给出参数；LangGraph 的 ToolNode 执行后把结果作为 ``ToolMessage`` 回填。
  最终措辞仍由下面的模板函数生成，因此引用、数字与前端契约保持可回归。

- **写走确定性工作流 + 审批**：``apply_leave``、``onboarding``、
  ``interview_schedule``、``salary_adjust`` 仍然走 ``_dispatch`` 里固定的
  ``_handle_*`` 顺序。原因不是“不会用 Agent”，而是审批单、幂等键、审计链
  和敏感操作拦截不能交给模型自由发挥：模型可以决定“想做什么”，但不能
  决定“是否已经审批”。这些工具也包装成了 ``@tool``，由确定性 handler
  直接调用（``_invoke_lc_tool``），执行入口和副作用边界没有变化。

- **为什么意图识别还用规则？** 教程默认离线、确定性、可回归。规则路由在这
  10 类 HR 请求上足够稳，并且每一步都能在 Trace 里解释“为什么走了这条分支”。
  真实模型模式下，读意图的“工具选择”已经交给 LangChain Agent；如果模型没有
  选择工具（或框架调用失败），``_read_tool`` 会回退到同一套 Toolbox 调用，
  保证 API 契约不被模型输出或框架可用性绑架。

生产环境替换点：把 ``classify_intent`` 换成 LLM 结构化输出；把模板换成 LLM
生成。但工具权限、审批中断、引用校验这三层必须保留。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Callable

from langchain.agents import create_agent
from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool
from langgraph.checkpoint.memory import InMemorySaver

try:  # 作为包导入
    from . import config
except ImportError:  # python app/backend/main.py
    import config  # type: ignore[no-redef]

# config 会把 code/ 加入 sys.path，所以 common.* 必须在 config 之后导入。
from common.lc import MockChatModel, get_chat_model
from common.data import candidate as find_candidate
from common.data import candidates, employee as find_employee, employees
from common.text import estimate_tokens, messages_tokens
from common.trace import Tracer

try:
    from .tools import PermissionDenied, SensitiveAction, ToolError, Toolbox
except ImportError:  # pragma: no cover
    from tools import PermissionDenied, SensitiveAction, ToolError, Toolbox  # type: ignore


SYSTEM_PROMPT = (
    "你是 Acme 科技（虚构）的 HR 智能服务台 Agent。"
    "你只能依据公司制度库、员工数据与工具结果回答；"
    "制度类问题必须给出文档编号、版本与条款；没有召回证据时明确拒答并转人工；"
    "敏感操作（安排面试、调薪）必须先创建审批单，审批通过后才能执行；"
    "展示候选人联系方式前必须脱敏。"
)

INTENT_LABELS = {
    "leave_balance": "识别为假期余额查询",
    "leave_policy": "识别为制度 / 规则查询",
    "apply_leave": "识别为请假申请",
    "candidate_search": "识别为候选人搜索",
    "candidate_query": "识别为候选人详情查询",
    "interview_schedule": "识别为面试安排（敏感操作）",
    "salary_adjust": "识别为薪资调整（敏感操作）",
    "onboarding": "识别为入职流程",
    "ticket_query": "识别为工单查询",
    "out_of_scope": "超出 HR 服务范围，转人工",
}

DEFAULT_SUGGESTIONS = {
    "leave_balance": ["帮我提交 3 天年假申请", "年假可以结转到什么时候？"],
    "leave_policy": ["我还有几天年假？", "帮我提交 3 天年假申请"],
    "apply_leave": ["查一下我的年假余额", "年假没休完可以结转吗？"],
    "candidate_search": ["看看候选人的详细信息", "安排这位候选人面试"],
    "candidate_query": ["安排这位候选人面试", "再推荐几位算法候选人"],
    "interview_schedule": ["查看待审批的申请", "换一个面试时间"],
    "salary_adjust": ["查看审批状态", "调薪需要哪些审批人？"],
    "onboarding": ["入职第一天要准备什么？", "查看入职流程进度"],
    "ticket_query": ["查一下其他工单", "工单处理 SLA 是多久？"],
    "out_of_scope": ["我还有几天年假？", "年假可以结转到什么时候？"],
}

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TICKET_RE = re.compile(r"T\d{7}", re.IGNORECASE)
EMPLOYEE_RE = re.compile(r"E\d{4}", re.IGNORECASE)
CANDIDATE_RE = re.compile(r"C\d{3}", re.IGNORECASE)
BAND_RE = re.compile(r"[PM]\d-\d", re.IGNORECASE)
DAYS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*天")
DATETIME_RE = re.compile(
    r"(\d{4}-\d{2}-\d{2})(?:[T\s]+(\d{1,2}):(\d{2}))?"
)

POLICY_DOMAINS = (
    "年假",
    "病假",
    "婚假",
    "产假",
    "陪产假",
    "丧假",
    "育儿假",
    "请假",
    "休假",
    "远程",
    "居家",
    "报销",
    "差旅",
    "住宿",
    "绩效",
    "晋升",
    "offer",
    "试用期",
    "入职",
    "加班",
    "调休",
    "考勤",
    "背调",
    "招聘",
    "面试",
    "编制",
    "隐私",
    "脱敏",
    "公积金",
    "社保",
    "工资",
    "薪资",
    "调薪",
    "培训",
    "体检",
    "候选人",
)

# 出现这些词时，用户更像在问“规则是什么”，而不是让 Agent 立即执行。
POLICY_QUESTION_MARKERS = (
    "制度",
    "规则",
    "流程",
    "政策",
    "标准",
    "条件",
    "规定",
    "要求",
    "口径",
    "审批人",
    "谁审批",
    "哪些人",
    "多久",
    "几天",
    "多少天",
    "什么时候",
    "怎么算",
    "如何",
    "是否",
    "能不能",
    "可以吗",
    "需要什么",
    "需要哪些",
    "材料",
    "准备",
    "保留",
    "期限",
)

OUT_OF_SCOPE_HINTS = (
    "天气",
    "年会",
    "食堂",
    "午餐吃什么",
    "停车",
    "股票",
    "彩票",
    "快递",
    "开除",
    "辞退",
    "裁员",
    "解除劳动",
    "帮我骂",
)

POSITION_HINTS = ("前端", "后端", "算法", "测试", "产品", "HRBP", "招聘", "大客户", "销售", "数据")
CITY_HINTS = ("上海", "北京", "深圳", "杭州", "广州", "成都")


class AgentInputError(Exception):
    """请求本身不合法（例如 employee_id 不存在），API 层转换成 400。"""


def classify_intent(message: str) -> str:
    """10 个意图的确定性路由。顺序即优先级。

    先判断“用户要 Agent 做事”，再判断“用户在问规则”，
    避免把“调薪需要哪些审批人”误判成一次调薪写操作。
    """
    text = (message or "").strip()
    if not text:
        return "out_of_scope"
    lowered = text.lower()

    if TICKET_RE.search(text) or "工单" in text:
        return "ticket_query"

    if any(hint in text for hint in OUT_OF_SCOPE_HINTS):
        return "out_of_scope"

    candidate_names = [person["name"] for person in candidates()]
    policy_question = any(marker in text for marker in POLICY_QUESTION_MARKERS)

    # 明确的写操作请求（提交 / 申请请假）优先于制度问答。
    if "假" in text and any(key in text for key in ("提交", "申请", "请假")):
        if not any(
            key in text
            for key in ("流程", "规则", "制度", "政策", "怎么", "如何", "需要", "多久", "材料", "条件")
        ):
            return "apply_leave"

    if "假" in text and any(
        key in text for key in ("还有", "还剩", "剩余", "余额", "我的年假", "我有")
    ):
        return "leave_balance"

    # 制度问答：命中领域词 + 疑问词，且没有给出具体薪资带宽。
    if (
        policy_question
        and not BAND_RE.search(text)
        and any(domain in lowered for domain in POLICY_DOMAINS)
    ):
        return "leave_policy"

    if any(key in text for key in ("调薪", "涨薪", "薪资调整", "薪酬调整")):
        return "salary_adjust"
    if (
        any(key in text for key in ("薪资", "工资", "带宽"))
        and any(key in text for key in ("调", "改", "升", "调整"))
    ):
        return "salary_adjust"

    if "面试" in text and any(
        key in text for key in ("安排", "预约", "约", "排期", "定在")
    ):
        return "interview_schedule"

    if "入职" in text:
        onboarding_request = any(
            key in text for key in ("办理入职", "入职日期", "启动入职", "入职安排")
        ) or any(name in text for name in candidate_names)
        if onboarding_request:
            return "onboarding"
        if not policy_question:
            return "onboarding"

    if "候选人" in text:
        if any(key in text for key in ("找", "推荐", "搜", "筛", "哪些", "几位", "有没有", "查一下")):
            return "candidate_search"
        return "candidate_query"

    if any(name in text for name in candidate_names) and any(
        key in text for key in ("哪一步", "进度", "状态", "情况", "详情", "怎么样", "到哪")
    ):
        return "candidate_query"

    if any(domain in lowered for domain in POLICY_DOMAINS):
        return "leave_policy"

    if "假" in text:
        return "leave_policy"

    return "out_of_scope"


def _extract_dates(text: str) -> list[str]:
    seen: list[str] = []
    for match in DATE_RE.findall(text):
        if match not in seen:
            seen.append(match)
    return seen


def _extract_days(text: str, dates: list[str]) -> float | None:
    match = DAYS_RE.search(text)
    if match:
        return float(match.group(1))
    if len(dates) >= 2:
        try:
            start = datetime.strptime(dates[0], "%Y-%m-%d")
            end = datetime.strptime(dates[1], "%Y-%m-%d")
        except ValueError:
            return None
        return float((end - start).days + 1)
    if dates:
        return 1.0
    return None


def _extract_datetime(text: str) -> datetime | None:
    match = DATETIME_RE.search(text)
    if not match:
        return None
    date_part, hour, minute = match.group(1), match.group(2), match.group(3)
    try:
        base = datetime.strptime(date_part, "%Y-%m-%d")
    except ValueError:
        return None
    return base.replace(
        hour=int(hour) if hour else 10,
        minute=int(minute) if minute else 0,
        tzinfo=config.TZ,
    )


def _extract_employee(text: str) -> dict | None:
    match = EMPLOYEE_RE.search(text)
    if match:
        person = find_employee(match.group().upper())
        if person:
            return person
    for person in sorted(employees(), key=lambda item: len(item["name"]), reverse=True):
        if person["name"] in text:
            return person
    return None


def _extract_candidate(text: str) -> dict | None:
    match = CANDIDATE_RE.search(text)
    if match:
        person = find_candidate(match.group().upper())
        if person:
            return person
    for person in sorted(candidates(), key=lambda item: len(item["name"]), reverse=True):
        if person["name"] in text:
            return person
    return None


def _extract_skills(text: str) -> list[str]:
    lowered = text.casefold()
    skills: list[str] = []
    for person in candidates():
        for skill in person["skills"]:
            if skill.casefold() in lowered and skill not in skills:
                skills.append(skill)
    return skills


def _extract_position(text: str) -> str | None:
    for hint in POSITION_HINTS:
        if hint in text:
            return hint
    return None


def _extract_min_years(text: str) -> int:
    match = re.search(r"(\d+)\s*年", text)
    return int(match.group(1)) if match else 0


def _extract_city(text: str) -> str | None:
    for city in CITY_HINTS:
        if city in text:
            return city
    return None


@dataclass
class Turn:
    message: str
    actor: str
    session_id: str
    now: datetime
    intent: str
    steps: list[dict] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    status: str = "completed"
    reply: str = ""
    approval: dict | None = None
    facts: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    def step(
        self,
        step_type: str,
        title: str,
        detail: str,
        *,
        status: str = "ok",
        data: dict | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        self.steps.append(
            {
                "index": len(self.steps) + 1,
                "type": step_type,
                "title": title,
                "detail": detail,
                "status": status,
                "duration_ms": round(duration_ms, 2),
                "data": data or {},
            }
        )


@dataclass
class AgentResult:
    payload: dict
    tools_used: list[str]
    citations: list[dict]


# ---------------------------------------------------------------------------
# LangChain / LangGraph 集成层
# ---------------------------------------------------------------------------
# 这一层的原则：框架负责“编排与工具选择”，Toolbox 负责“权限、幂等、脱敏”。
# 工具函数只做参数整理，然后把调用委托给 Toolbox；因此旧有的 RBAC、PII 脱敏、
# 幂等键、审批拦截全部原样保留，Agent 不可能绕过它们。
#
# 为什么读意图交给 create_agent，而写意图不交？
# - 读：没有副作用，模型选错工具最多是多查一次；ToolNode 的回填结果正好可以
#   交给模板生成可校验的引用和数字。
# - 写：审批单是否创建、幂等键是否复用、审计链顺序，都必须是确定的。让模型
#   决定“调用哪个工具”可以，但不能让它决定“是否已经审批”。所以写路径仍在
#   ``_dispatch`` 里按固定顺序执行，只是执行单元换成了 @tool 包装。
# ---------------------------------------------------------------------------


@dataclass
class LCToolCall:
    """一次 LangChain 工具执行的记录，用于回填 steps / tools_used。"""

    name: str
    args: dict
    result: Any = None
    error: Exception | None = None
    duration_ms: float = 0.0


@dataclass
class LCTurnContext:
    """单次 Agent 调用的运行时上下文，通过 RunnableConfig 注入到工具。

    把 Toolbox / actor 放在 config 而不是工具参数里，有两个好处：
    1. 模型看不到 ``actor``，无法通过改参数来越权；
    2. 同一个工具定义可以服务所有请求，执行时再取当前请求的上下文。
    """

    toolbox: Toolbox
    actor: str
    message: str
    calls: list[LCToolCall] = field(default_factory=list)

    def record(
        self,
        name: str,
        args: dict,
        *,
        result: Any = None,
        error: Exception | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        self.calls.append(
            LCToolCall(
                name=name,
                args=dict(args),
                result=result,
                error=error,
                duration_ms=duration_ms,
            )
        )


def _hr_context(config: RunnableConfig | None) -> LCTurnContext:
    """从 LangChain 运行时配置里取回本轮的 Toolbox 上下文。"""
    configurable = (config or {}).get("configurable") or {}
    context = configurable.get("hr_context")
    if not isinstance(context, LCTurnContext):
        raise ToolError("LangChain 工具缺少运行时上下文，本次调用被拒绝")
    return context


def _execute_read_tool(
    context: LCTurnContext,
    name: str,
    args: dict,
    action: Callable[[], Any],
) -> dict:
    """执行只读工具并把结果/异常记在上下文里。

    只读工具不把异常直接抛给 LangGraph：先记录，再让 ToolNode 正常收尾；
    ``HRAgent._read_tool`` 会在 Agent 结束后重新抛出，交给现有的
    ``PermissionDenied → 转人工`` / ``ToolError → error`` 分支处理。
    """
    started = time.perf_counter()
    try:
        result = action()
    except Exception as exc:  # noqa: BLE001 - 业务异常要转换成结构化工具结果
        context.record(
            name,
            args,
            error=exc,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return {
            "ok": False,
            "tool": name,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    context.record(
        name,
        args,
        result=result,
        duration_ms=(time.perf_counter() - started) * 1000,
    )
    return {"ok": True, "tool": name, "result": result}


def _is_draft_policy_question(message: str) -> bool:
    return "2027" in message and (
        "远程" in message or "讨论稿" in message or "草案" in message
    )


def _policy_retrieval(toolbox: Toolbox, message: str, *, top_k: int = 4) -> dict:
    """制度检索的确定性策略：普通问题走一次混合检索，2027 讨论稿问题额外对照现行版。

    返回 ``{"citations": [...], "draft_question": bool}``，由格式化函数决定
    怎么措辞；这样 LangChain 工具和回退路径用的是同一套检索口径。
    """
    if _is_draft_policy_question(message):
        hits = toolbox.search_policy(
            "远程办公 2027 讨论稿 是否生效", top_k=4, include_drafts=True
        )
        active_hits = toolbox.search_policy("远程办公 每周最多 2 天", top_k=2)
        draft_citation = next(
            (item for item in hits if item["doc_id"] == "remote-2027-draft"), None
        )
        active_citation = next(
            (item for item in active_hits if item["doc_id"] == "remote-2025"), None
        ) or next(
            (item for item in hits if item["doc_id"] == "remote-2025"), None
        )
        citations = [
            item for item in (draft_citation, active_citation) if item is not None
        ]
        return {"citations": citations, "draft_question": True}
    return {
        "citations": toolbox.search_policy(message, top_k=top_k),
        "draft_question": False,
    }


# ---------------------------------------------------------------------------
# 只读工具（绑定给 create_agent，由模型选择）
# ---------------------------------------------------------------------------
@tool(
    "get_leave_balance",
    description="查询当前演示身份（或指定员工）的年假与病假余额。只读，不会修改任何数据。",
)
def lc_get_leave_balance(
    employee_id: str = "",
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """查询年假/病假余额；普通员工只能查自己，HR 角色可以代查。"""
    context = _hr_context(config)
    target = (employee_id or "").strip() or context.actor
    args = {"employee_id": target}
    return _execute_read_tool(
        context,
        "get_leave_balance",
        args,
        lambda: context.toolbox.get_leave_balance(target, context.actor),
    )


@tool(
    "search_policy",
    description="在制度库做混合检索（BM25 + 向量），返回可引用的片段、版本与条款。只读。",
)
def lc_search_policy(
    query: str,
    top_k: int = 4,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """检索制度依据；没有召回证据时返回空列表，由上层拒答转人工。"""
    context = _hr_context(config)
    args = {"query": query, "top_k": top_k}
    return _execute_read_tool(
        context,
        "search_policy",
        args,
        lambda: _policy_retrieval(context.toolbox, query, top_k=top_k),
    )


@tool(
    "search_candidates",
    description="按技能、岗位、年限、城市筛选候选人；联系方式返回前已脱敏。只读。",
)
def lc_search_candidates(
    skills: list[str] | None = None,
    position: str | None = None,
    min_years: int = 0,
    city: str | None = None,
    top_k: int = 5,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """筛选候选人；RBAC 由 Toolbox 校验（仅招聘相关角色可访问）。"""
    context = _hr_context(config)
    args = {
        "skills": list(skills or []),
        "position": position,
        "min_years": min_years,
        "city": city,
        "top_k": top_k,
    }
    return _execute_read_tool(
        context,
        "search_candidates",
        args,
        lambda: context.toolbox.search_candidates(
            actor=context.actor,
            skills=args["skills"],
            position=position,
            min_years=min_years,
            city=city,
            top_k=top_k,
        ),
    )


@tool(
    "get_candidate",
    description="按姓名或编号查询候选人详情；手机号与邮箱在 Toolbox 内脱敏。只读。",
)
def lc_get_candidate(
    identifier: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """查询候选人详情；跨人访问由 Toolbox 做 RBAC 校验。"""
    context = _hr_context(config)
    args = {"identifier": identifier}
    return _execute_read_tool(
        context,
        "get_candidate",
        args,
        lambda: context.toolbox.get_candidate(identifier, context.actor),
    )


@tool(
    "get_ticket",
    description="按工单号查询工单状态、优先级、负责人与 SLA。只读。",
)
def lc_get_ticket(
    ticket_id: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """查询工单；普通员工只能看自己的工单，HR 角色可以跨人查询。"""
    context = _hr_context(config)
    args = {"ticket_id": ticket_id}
    return _execute_read_tool(
        context,
        "get_ticket",
        args,
        lambda: context.toolbox.get_ticket(ticket_id, context.actor),
    )


# ---------------------------------------------------------------------------
# 写 / 敏感工具（@tool 暴露，但由确定性 handler 直接调用）
# ---------------------------------------------------------------------------
# 这些工具不会绑定给 create_agent：审批链路必须由代码控制。直接
# ``tool.invoke(...)`` 时，Toolbox 抛出的 SensitiveAction / PermissionDenied /
# ToolError 会原样传播，交给 HRAgent.run 的统一异常分支处理。
# ---------------------------------------------------------------------------
@tool(
    "check_leave_eligibility",
    description="校验请假余额、提前工作日与日期冲突。只读校验，不创建申请。",
)
def lc_check_leave_eligibility(
    employee_id: str,
    start_date: str,
    end_date: str,
    days: float,
    leave_type: str,
    ignore_request_id: str | None = None,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """调用 Toolbox 的确定性校验；权限与冲突判断都在 Toolbox 内。"""
    context = _hr_context(config)
    return context.toolbox.check_leave_eligibility(
        employee_id,
        start_date,
        end_date,
        days,
        leave_type,
        context.actor,
        ignore_request_id=ignore_request_id,
    )


@tool(
    "submit_leave_request",
    description="幂等提交请假申请。写操作，重复调用返回同一业务单号。",
)
def lc_submit_leave_request(
    employee_id: str,
    start_date: str,
    end_date: str,
    days: float,
    leave_type: str,
    idempotency_key: str | None = None,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """调用 Toolbox 的幂等写入口；审计与幂等键由 Store 负责。"""
    context = _hr_context(config)
    return context.toolbox.submit_leave_request(
        employee_id,
        start_date,
        end_date,
        days,
        leave_type,
        context.actor,
        idempotency_key,
    )


@tool(
    "schedule_interview",
    description="创建面试日程。敏感写操作，必须审批；未审批前不会产生任何日程副作用。",
)
def lc_schedule_interview(
    candidate: str,
    scheduled_at: str,
    interviewer: str | None = None,
    mode: str = "视频",
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """调用 Toolbox 时只会抛 SensitiveAction，由 run() 创建审批单并中断。"""
    context = _hr_context(config)
    return context.toolbox.schedule_interview(
        actor=context.actor,
        candidate=candidate,
        scheduled_at=scheduled_at,
        interviewer=interviewer,
        mode=mode,
    )


@tool(
    "adjust_salary",
    description="调整员工薪资带宽。敏感写操作，必须审批；未审批前不会修改薪资数据。",
)
def lc_adjust_salary(
    employee: str,
    new_band: str,
    reason: str | None = None,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """调用 Toolbox 时只会抛 SensitiveAction，由 run() 创建审批单并中断。"""
    context = _hr_context(config)
    return context.toolbox.adjust_salary(
        actor=context.actor,
        employee=employee,
        new_band=new_band,
        reason=reason,
    )


@tool(
    "start_onboarding",
    description="启动候选人入职状态机。写操作，幂等键为候选人 + 入职日期。",
)
def lc_start_onboarding(
    candidate: str,
    start_date: str,
    config: Annotated[RunnableConfig, InjectedToolArg] = None,  # type: ignore[assignment]
) -> dict:
    """调用 Toolbox 的入职状态机入口；步骤与审计由 Store 负责。"""
    context = _hr_context(config)
    return context.toolbox.start_onboarding(
        actor=context.actor,
        candidate=candidate,
        start_date=start_date,
    )


LC_READ_TOOLS = [
    lc_get_leave_balance,
    lc_search_policy,
    lc_search_candidates,
    lc_get_candidate,
    lc_get_ticket,
]

LC_WRITE_TOOLS = [
    lc_check_leave_eligibility,
    lc_submit_leave_request,
    lc_schedule_interview,
    lc_adjust_salary,
    lc_start_onboarding,
]


def _read_tool_script(tool_name: str, args: dict) -> Callable[[list, Any], dict]:
    """离线 MockChatModel 的脚本：第一轮选工具，工具回填后结束。

    这不是“假装调用”：create_agent 仍然会走 model → tools → model 的真实
    LangGraph 循环；脚本只决定 Mock 模型在每一轮返回什么。真实模型模式下
    get_chat_model() 会忽略 script，由模型自己选择工具；如果它没有调用工具，
    ``HRAgent._read_tool`` 会回退到同一套 Toolbox 调用。
    """

    def script(messages: list, tools: Any) -> dict:
        if any(isinstance(message, ToolMessage) for message in messages):
            return {"content": ""}
        return {
            "tool_calls": [
                {
                    "name": tool_name,
                    "args": dict(args),
                    "id": f"call_{tool_name}",
                }
            ]
        }

    return script


class HRAgent:
    def __init__(self, store, rag) -> None:
        self.store = store
        self.rag = rag
        self.toolbox = Toolbox(store, rag)
        self.langchain_runs = 0  # 诊断用：本轮进程里真正跑过多少次 create_agent

    # ------------------------------------------------------------------
    # 入口
    # ------------------------------------------------------------------
    def run(
        self,
        message: str,
        employee_id: str,
        *,
        session_id: str | None = None,
        idempotency_key: str | None = None,
        now: datetime | None = None,
    ) -> AgentResult:
        message = (message or "").strip()
        if not message:
            raise AgentInputError("消息不能为空")
        if len(message) > config.MAX_MESSAGE_CHARS:
            raise AgentInputError(f"消息过长（上限 {config.MAX_MESSAGE_CHARS} 字）")
        actor_person = find_employee((employee_id or "").strip())
        if not actor_person:
            raise AgentInputError(f"员工不存在：{employee_id or '（空）'}")

        actor = actor_person["id"]
        moment = now or self.store.now()
        session = self.store.get_or_create_session(session_id, actor)
        history = [dict(item) for item in session.messages[-18:]]
        tracer = Tracer("hr-agent-chat")

        route_started = time.perf_counter()
        intent = classify_intent(message)
        turn = Turn(
            message=message,
            actor=actor,
            session_id=session.id,
            now=moment,
            intent=intent,
        )
        turn.step(
            "llm",
            "理解问题",
            INTENT_LABELS.get(intent, "识别意图"),
            duration_ms=(time.perf_counter() - route_started) * 1000,
        )

        try:
            self._dispatch(turn, idempotency_key)
        except SensitiveAction as exc:
            self._interrupt_for_approval(turn, exc)
        except PermissionDenied as exc:
            self._escalate(turn, str(exc), category="权限")
        except ToolError as exc:
            turn.status = "error"
            turn.reply = (
                f"这次请求没有完成：{exc}。\n\n"
                "你可以补充更具体的信息再试；如果仍然失败，我可以帮你转人工。"
            )
            turn.facts.append(f"本次失败：{exc}")
            turn.suggestions = ["查一下我的年假余额", "帮我转人工"]
        except Exception as exc:  # noqa: BLE001 - Agent 不能把 500 直接抛给前端
            turn.status = "error"
            turn.reply = f"服务处理时出现异常（{type(exc).__name__}），本次没有产生任何业务变更。请稍后重试或转人工。"
            turn.facts.append(f"本次异常：{type(exc).__name__}")
            turn.suggestions = ["重试一次", "帮我转人工"]

        final_started = time.perf_counter()
        if not turn.reply:
            turn.reply = "我暂时无法生成回答，建议转人工处理。"
        detail = {
            "completed": "组合工具结果与制度引用，附上下一步建议",
            "pending_approval": "说明风险边界与审批状态，未执行副作用",
            "escalated": "说明拒答原因并创建人工工单",
            "error": "说明失败原因与可重试方式",
        }.get(turn.status, "生成回答")
        turn.step(
            "final",
            "生成回答",
            detail,
            duration_ms=(time.perf_counter() - final_started) * 1000,
        )

        suggestions = [item for item in turn.suggestions if item]
        for fallback in DEFAULT_SUGGESTIONS.get(intent, DEFAULT_SUGGESTIONS["out_of_scope"]):
            if len(suggestions) >= 2:
                break
            if fallback not in suggestions:
                suggestions.append(fallback)
        turn.suggestions = suggestions[:2]

        for fact in turn.facts:
            self.store.add_fact(session, fact)
        self.store.append_turn(session, message, turn.reply)

        prompt_messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history, {"role": "user", "content": message}]
        prompt_tokens = messages_tokens(prompt_messages)
        completion_tokens = estimate_tokens(turn.reply)
        total_tokens = prompt_tokens + completion_tokens
        approval_payload = None
        if turn.approval:
            approval_payload = {
                key: value
                for key, value in turn.approval.items()
                if key != "session_id"
            }
        payload = {
            "session_id": session.id,
            "trace_id": tracer.trace_id,
            "reply": turn.reply,
            "intent": turn.intent,
            "status": turn.status,
            "steps": turn.steps,
            "citations": turn.citations,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": config.estimate_cost_usd(prompt_tokens, completion_tokens),
            },
            "approval": approval_payload,
            "memory": self.store.memory_payload(actor, session.facts),
            "suggestions": turn.suggestions,
        }
        return AgentResult(payload=payload, tools_used=list(turn.tools_used), citations=list(turn.citations))

    # ------------------------------------------------------------------
    # LangChain 调用：读意图走 create_agent，写意图直接调 @tool
    # ------------------------------------------------------------------
    def _invoke_read_agent(
        self, turn: Turn, tool_name: str, args: dict
    ) -> LCTurnContext | None:
        """用 create_agent 跑一次只读工具选择；失败或无工具调用时返回 None。

        返回值是上下文而不是最终文本：我们只需要 ToolNode 执行后的真实工具
        结果，最终回答仍交给 ``_format_*`` 模板，保证引用与数字可回归。
        """
        context = LCTurnContext(
            toolbox=self.toolbox,
            actor=turn.actor,
            message=turn.message,
        )
        script = _read_tool_script(tool_name, args)
        # 默认 mock 模式强制使用 MockChatModel，避免机器上恰好有 Key 时测试
        # 意外联网；只有显式改了 HR_LLM_MODE 才走真实模型。
        if config.LLM_MODE == "mock":
            model = MockChatModel(script=script)
        else:
            model = get_chat_model(script=script)

        try:
            # 只读 Agent 不需要跨轮状态：每次请求一个独立的 InMemorySaver，
            # 既演示了 checkpointer + thread_id，又不会让内存随请求数增长。
            agent = create_agent(
                model=model,
                tools=LC_READ_TOOLS,
                system_prompt=SYSTEM_PROMPT,
                checkpointer=InMemorySaver(),
            )
            agent.invoke(
                {"messages": [{"role": "user", "content": turn.message}]},
                config={
                    "configurable": {
                        "thread_id": turn.session_id,
                        "hr_context": context,
                    },
                    "recursion_limit": 6,
                },
            )
        except Exception:  # noqa: BLE001 - 框架/网络问题回退到确定性路径
            return None

        if not context.calls:
            # 真实模型可能直接回答而没有调用工具；回退到 Toolbox 直调。
            return None
        self.langchain_runs += 1
        return context

    def _read_tool(
        self,
        turn: Turn,
        tool_name: str,
        args: dict,
        fallback: Callable[[], Any],
    ) -> tuple[Any, float]:
        """优先通过 create_agent 执行只读工具，失败时回退到 Toolbox 直调。

        返回 ``(result, duration_ms)``，供格式化函数写进原来的 tool/retrieval
        step。业务异常（权限不足、工单不存在）在 Agent 路径里会被记录后再
        抛出，因此 ``run`` 的异常分支完全复用。
        """
        context = self._invoke_read_agent(turn, tool_name, args)
        if context is not None:
            # 真实模型可能选错工具；只有它真的调用了期望的工具，才采用其结果，
            # 否则回退到确定性 Toolbox 调用，避免用错 schema 去格式化。
            matching = [call for call in context.calls if call.name == tool_name]
            if matching:
                call = matching[-1]
                if call.error is not None:
                    raise call.error
                return call.result, call.duration_ms

        started = time.perf_counter()
        result = fallback()
        return result, (time.perf_counter() - started) * 1000

    def _invoke_lc_tool(self, turn: Turn, lc_tool: Any, args: dict) -> Any:
        """确定性 handler 直接调用 @tool 包装的写/敏感工具。

        Toolbox 抛出的 ``SensitiveAction`` / ``PermissionDenied`` / ``ToolError``
        会原样穿透（LangChain 不会包装异常），所以审批中断与错误分支不变。
        """
        context = LCTurnContext(
            toolbox=self.toolbox,
            actor=turn.actor,
            message=turn.message,
        )
        return lc_tool.invoke(
            args,
            config={"configurable": {"hr_context": context}},
        )

    # ------------------------------------------------------------------
    # 路由分发
    # ------------------------------------------------------------------
    def _dispatch(self, turn: Turn, idempotency_key: str | None) -> None:
        handlers = {
            "leave_balance": self._handle_leave_balance,
            "leave_policy": self._handle_leave_policy,
            "apply_leave": lambda item: self._handle_apply_leave(item, idempotency_key),
            "candidate_search": self._handle_candidate_search,
            "candidate_query": self._handle_candidate_query,
            "interview_schedule": self._handle_interview,
            "salary_adjust": self._handle_salary,
            "onboarding": self._handle_onboarding,
            "ticket_query": self._handle_ticket,
            "out_of_scope": self._handle_out_of_scope,
        }
        handlers.get(turn.intent, self._handle_out_of_scope)(turn)

    # ------------------------------------------------------------------
    # 审批中断 / 转人工
    # ------------------------------------------------------------------
    def _interrupt_for_approval(self, turn: Turn, exc: SensitiveAction) -> None:
        turn.tools_used.append(exc.action)
        turn.step(
            "tool",
            exc.action,
            "高风险写操作：已拦截，未执行任何副作用",
            status="pending",
            data={"action": exc.action, "risk": exc.risk},
        )
        approval = self.store.create_approval(
            action=exc.action,
            summary=exc.summary,
            risk=exc.risk,
            payload=exc.payload,
            session_id=turn.session_id,
            requested_by=turn.actor,
        )
        turn.approval = approval
        turn.status = "pending_approval"
        turn.step(
            "approval",
            "创建审批单",
            f"{approval['id']} · {approval['summary']}",
            status="pending",
            data={
                "approval_id": approval["id"],
                "action": approval["action"],
                "risk": approval["risk"],
            },
        )
        self.store.record_audit(
            turn.actor, "create_approval", approval["id"], approval["summary"]
        )
        if exc.action == "adjust_salary":
            turn.reply = (
                f"已提交调薪审批（审批单 **{approval['id']}**，风险 **high**）："
                f"{approval['summary']}。\n\n"
                "审批通过后才会执行变更并写入审计日志；当前薪资数据没有发生任何改动。"
            )
            turn.suggestions = ["查看审批状态", "调薪需要哪些审批人？"]
        elif exc.action == "schedule_interview":
            turn.reply = (
                f"已提交面试安排审批（审批单 **{approval['id']}**，风险 **high**）："
                f"{approval['summary']}。\n\n"
                "审批通过后才会创建日程并通知候选人；当前没有产生任何日程副作用。"
            )
            turn.suggestions = ["查看待审批的申请", "换一个面试时间"]
        else:
            turn.reply = (
                f"该操作需要人工审批（审批单 **{approval['id']}**），审批通过后才会执行。"
            )
        turn.facts.append(f"待审批：{approval['action']}（{approval['id']}）")

    def _escalate(self, turn: Turn, reason: str, *, category: str = "其他") -> None:
        ticket = self.store.create_escalation(
            actor=turn.actor, reason=reason, category=category
        )
        turn.status = "escalated"
        if category == "权限":
            turn.reply = (
                f"{reason}，我没有执行任何操作。\n\n"
                f"已为你转人工（工单号 **{ticket['id']}**），HR 会核实权限后跟进。"
            )
            turn.facts.append(f"已转人工：权限不足（{ticket['id']}）")
        else:
            turn.reply = (
                f"制度库中没有找到能支撑这个问题的依据，我不会编造答案。\n\n"
                f"已为你转人工（工单号 **{ticket['id']}**），HR 会补充口径后回复你。"
            )
            turn.facts.append(f"已转人工：制度检索无依据（{ticket['id']}）")
        turn.suggestions = ["查一下我的年假余额", "年假可以结转到什么时候？"]

    def _escalate_out_of_scope(self, turn: Turn, reason: str) -> None:
        ticket = self.store.create_escalation(actor=turn.actor, reason=reason, category="其他")
        turn.status = "escalated"
        turn.reply = (
            "这个问题超出我的服务范围，无法直接处理。\n\n"
            f"已为你转人工（工单号 **{ticket['id']}**），HR 会在 1 个工作日内跟进。"
        )
        turn.facts.append(f"已转人工：超出服务范围（{ticket['id']}）")

    # ------------------------------------------------------------------
    # 1. 年假余额
    # ------------------------------------------------------------------
    def _handle_leave_balance(self, turn: Turn) -> None:
        data, duration_ms = self._read_tool(
            turn,
            "get_leave_balance",
            {"employee_id": turn.actor},
            lambda: self.toolbox.get_leave_balance(turn.actor, turn.actor),
        )
        self._format_leave_balance(turn, data, duration_ms)

    def _format_leave_balance(
        self, turn: Turn, data: dict, duration_ms: float
    ) -> None:
        turn.tools_used.append("get_leave_balance")
        turn.step(
            "tool",
            "get_leave_balance",
            f"{data['employee_id']} → 剩余 {data['annual_remaining']} 天",
            data={
                "annual_total": data["annual_total"],
                "annual_used": data["annual_used"],
                "annual_remaining": data["annual_remaining"],
                "sick_remaining": data["sick_remaining"],
            },
            duration_ms=duration_ms,
        )
        turn.reply = (
            f"你还有 **{data['annual_remaining']} 天** 年假"
            f"（{data['year']} 年度额度 {data['annual_total']} 天，已用 {data['annual_used']} 天）。\n\n"
            f"病假额度 {data['sick_total']} 天，已用 {data['sick_used']} 天，还剩 {data['sick_remaining']} 天。\n\n"
            "需要的话，我可以帮你校验日期并提交年假申请。"
        )
        turn.facts.append(f"本次查询：年假余额（剩余 {data['annual_remaining']} 天）")
        turn.suggestions = ["帮我提交 3 天年假申请", "年假可以结转到什么时候？"]

    # ------------------------------------------------------------------
    # 2. 制度查询
    # ------------------------------------------------------------------
    def _handle_leave_policy(self, turn: Turn) -> None:
        payload, duration_ms = self._read_tool(
            turn,
            "search_policy",
            {"query": turn.message, "top_k": 4},
            lambda: _policy_retrieval(self.toolbox, turn.message, top_k=4),
        )
        self._format_leave_policy(turn, payload, duration_ms)

    def _format_leave_policy(
        self, turn: Turn, payload: dict, duration_ms: float
    ) -> None:
        citations = list(payload.get("citations") or [])
        draft_question = bool(payload.get("draft_question"))
        turn.tools_used.append("search_policy")
        turn.citations = citations
        turn.step(
            "retrieval",
            "search_policy",
            f"「{turn.message[:24]}」→ 命中 {len(citations)} 个片段",
            status="ok" if citations else "error",
            data={
                "matches": len(citations),
                "doc_ids": [item["doc_id"] for item in citations],
            },
            duration_ms=duration_ms,
        )

        if not citations:
            self._escalate(turn, f"制度库未找到依据：{turn.message}", category="制度")
            return

        if draft_question:
            draft_citation = next(
                (item for item in citations if item["doc_id"] == "remote-2027-draft"), None
            )
            active_citation = next(
                (item for item in citations if item["doc_id"] == "remote-2025"), None
            )
            turn.citations = [
                item for item in (draft_citation, active_citation) if item is not None
            ]
            if draft_citation and active_citation:
                turn.reply = (
                    f"《{draft_citation['title']}》（版本 {draft_citation['version']}）目前是"
                    "**讨论稿，尚未生效**，不能作为审批依据。\n\n"
                    f"当前执行《{active_citation['title']}》（版本 {active_citation['version']}）："
                    "每周最多申请 2 天远程办公，试用期内员工不适用。\n\n"
                    "讨论稿拟将每周远程天数调整为 3 天、取消“周二周三必须到岗”，但这些改动需批准后才会生效。"
                )
            else:
                turn.reply = (
                    "关于 2027 远程办公的内容目前仍是讨论稿，未生效，不能作为审批依据；"
                    "当前仍执行 2025 版《远程办公管理办法》，每周最多 2 天。"
                )
            turn.facts.append("本次查询：2027 远程办公讨论稿（未生效）")
            turn.suggestions = ["当前远程办公规则是什么？", "我还有几天年假？"]
            return

        main = citations[0]
        reply = (
            f"根据《{main['title']}》（版本 {main['version']}）「{main['heading']}」：\n\n"
            f"{main['snippet']}"
        )
        second = next(
            (
                item
                for item in citations[1:]
                if (item["doc_id"], item["heading"]) != (main["doc_id"], main["heading"])
                and item["score"] >= main["score"] * 0.7
            ),
            None,
        )
        if second:
            reply += (
                f"\n\n补充依据：《{second['title']}》（版本 {second['version']}）"
                f"「{second['heading']}」：\n{second['snippet']}"
            )
        reply += "\n\n以上是制度库中当前生效版本的口径；具体审批仍以 HR 系统流程为准。"
        turn.reply = reply
        # 只把真正写进回答的片段列为引用，避免前端“引用来源”里出现无关条款。
        turn.citations = [item for item in (main, second) if item is not None]
        turn.facts.append(f"本次查询：制度「{turn.message[:18]}」")
        turn.suggestions = ["我还有几天年假？", "帮我提交 3 天年假申请"]

    # ------------------------------------------------------------------
    # 3. 请假申请
    # ------------------------------------------------------------------
    def _handle_apply_leave(self, turn: Turn, idempotency_key: str | None) -> None:
        dates = _extract_dates(turn.message)
        days = _extract_days(turn.message, dates)
        if not dates or days is None:
            turn.reply = (
                "请告诉我请假的起止日期和天数，例如："
                "“帮我提交 2026-12-01 到 2026-12-03 的 3 天年假申请”。"
            )
            turn.suggestions = ["帮我提交 3 天年假申请", "查一下我的年假余额"]
            return
        start_date = dates[0]
        end_date = dates[1] if len(dates) > 1 else dates[0]
        leave_type = "sick" if "病假" in turn.message else "annual"
        key = idempotency_key or (
            f"leave:{turn.actor}:{start_date}:{end_date}:{days:g}:{leave_type}"
        )
        existing_id = self.store.recall_idempotent(key)

        started = time.perf_counter()
        # 写路径仍由固定顺序驱动：先校验、再提交；这里只是把执行单元换成 @tool。
        eligibility = self._invoke_lc_tool(
            turn,
            lc_check_leave_eligibility,
            {
                "employee_id": turn.actor,
                "start_date": start_date,
                "end_date": end_date,
                "days": days,
                "leave_type": leave_type,
                "ignore_request_id": existing_id,
            },
        )
        turn.tools_used.append("check_leave_eligibility")
        turn.step(
            "tool",
            "check_leave_eligibility",
            "校验通过" if eligibility["ok"] else "校验未通过：" + "；".join(eligibility["reasons"]),
            status="ok" if eligibility["ok"] else "error",
            data={
                "ok": eligibility["ok"],
                "remaining": eligibility["remaining"],
                "advance_workdays": eligibility["advance_workdays"],
            },
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        if not eligibility["ok"]:
            reasons = "\n".join(f"- {reason}" for reason in eligibility["reasons"])
            turn.reply = (
                f"这次请假还不能提交：\n{reasons}\n\n"
                "我没有创建任何申请。可以调整日期或先确认余额后再试；需要人工协助可以转 HR。"
            )
            turn.facts.append("本次尝试提交请假：未通过资格校验")
            turn.suggestions = ["查一下我的年假余额", "年假可以结转到什么时候？"]
            return

        submitted = self._invoke_lc_tool(
            turn,
            lc_submit_leave_request,
            {
                "employee_id": turn.actor,
                "start_date": start_date,
                "end_date": end_date,
                "days": days,
                "leave_type": leave_type,
                "idempotency_key": key,
            },
        )
        turn.tools_used.append("submit_leave_request")
        request = submitted["request"]
        turn.step(
            "tool",
            "submit_leave_request",
            f"{request['id']} → 已提交（幂等键 {submitted['idempotency_key'][:32]}）",
            data={
                "request_id": request["id"],
                "status": request["status"],
                "replay": submitted["replay"],
            },
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        if submitted["replay"]:
            turn.reply = (
                f"该申请此前已经提交过（幂等重放，没有重复创建），单号 **{request['id']}**。\n\n"
                f"{request['start_date']} 至 {request['end_date']}，共 {request['days']:g} 天，"
                "状态：待直属主管审批。"
            )
        else:
            type_label = "病假" if request.get("leave_type") == "sick" else "年假"
            turn.reply = (
                f"已提交你的{type_label}申请（单号 **{request['id']}**）："
                f"{request['start_date']} 至 {request['end_date']}，共 {request['days']:g} 天。\n\n"
                "状态：待直属主管审批。审批通过后，"
                f"年假余额预计剩下 {submitted['projected_annual_remaining']:g} 天。"
            )
        turn.facts.append(f"已提交请假申请 {request['id']}")
        turn.suggestions = ["查一下我的年假余额", "年假没休完可以结转吗？"]

    # ------------------------------------------------------------------
    # 4. 候选人搜索
    # ------------------------------------------------------------------
    def _handle_candidate_search(self, turn: Turn) -> None:
        skills = _extract_skills(turn.message)
        position = _extract_position(turn.message)
        min_years = _extract_min_years(turn.message)
        city = _extract_city(turn.message)
        args = {
            "skills": skills,
            "position": position,
            "min_years": min_years,
            "city": city,
            "top_k": 3,
        }
        result, duration_ms = self._read_tool(
            turn,
            "search_candidates",
            args,
            lambda: self.toolbox.search_candidates(actor=turn.actor, **args),
        )
        self._format_candidate_search(turn, result, skills, position, min_years, city, duration_ms)

    def _format_candidate_search(
        self,
        turn: Turn,
        result: dict,
        skills: list[str],
        position: str | None,
        min_years: int,
        city: str | None,
        duration_ms: float,
    ) -> None:
        turn.tools_used.append("search_candidates")
        turn.step(
            "tool",
            "search_candidates",
            "筛选条件：" + "，".join(
                filter(
                    None,
                    [
                        f"技能={'/'.join(skills)}" if skills else "",
                        f"岗位={position}" if position else "",
                        f"年限≥{min_years}" if min_years else "",
                        f"城市={city}" if city else "",
                    ],
                )
            )
            or "全部候选人",
            data={"count": result["count"], "candidate_ids": result["candidate_ids"]},
            duration_ms=duration_ms,
        )
        if not result["count"]:
            turn.reply = (
                "没有找到符合条件的候选人。可以放宽技能、年限或城市再试；"
                "如果你有目标岗位，我也可以按岗位帮你筛。"
            )
            turn.facts.append("本次搜索候选人：无结果")
            turn.suggestions = ["推荐几位算法候选人", "帮我找会 Vue3 的前端候选人"]
            return

        lines: list[str] = []
        for index, person in enumerate(result["candidates"], start=1):
            matched = "、".join(person["matched_skills"]) or "—"
            lines.append(
                f"{index}. **{person['name']}**（{person['id']}）｜{person['position']}｜"
                f"{person['years']} 年｜{person['city']}｜阶段：{person['stage']}｜"
                f"评分 {person['score']}｜匹配技能：{matched}"
            )
        prefix = f"共找到 {result['count']} 位匹配候选人"
        if result["count"] > len(result["candidates"]):
            prefix += f"，先看前 {len(result['candidates'])} 位"
        turn.reply = (
            prefix + "：\n\n" + "\n".join(lines) + "\n\n"
            "联系方式已按《员工与候选人数据隐私规范》脱敏；需要完整信息请走 HR 系统申请。"
        )
        turn.facts.append("本次搜索候选人：" + "、".join(result["candidate_ids"]))
        turn.suggestions = ["看看候选人的详细信息", "安排这位候选人面试"]

    # ------------------------------------------------------------------
    # 5. 候选人详情
    # ------------------------------------------------------------------
    def _handle_candidate_query(self, turn: Turn) -> None:
        person = _extract_candidate(turn.message)
        if not person:
            turn.reply = "请提供候选人姓名或编号（例如 C003 / 王浩），我再查详情。"
            turn.suggestions = ["帮我找会 Vue3 的前端候选人", "推荐几位算法候选人"]
            return
        detail, duration_ms = self._read_tool(
            turn,
            "get_candidate",
            {"identifier": person["id"]},
            lambda: self.toolbox.get_candidate(person["id"], turn.actor),
        )
        self._format_candidate_query(turn, detail, duration_ms)

    def _format_candidate_query(
        self, turn: Turn, detail: dict, duration_ms: float
    ) -> None:
        turn.tools_used.append("get_candidate")
        turn.step(
            "tool",
            "get_candidate",
            f"{detail['name']}（{detail['id']}）→ 阶段 {detail['stage']}",
            data={
                "candidate_id": detail["id"],
                "stage": detail["stage"],
                "score": detail["score"],
            },
            duration_ms=duration_ms,
        )
        note = detail.get("note") or ""
        interview_note = detail.get("interview_note")
        turn.reply = (
            f"**{detail['name']}**（{detail['id']}）目前在 **{detail['stage']}** 阶段，"
            f"{detail['position']}｜{detail['years']} 年经验｜{detail['city']}｜评分 {detail['score']}。\n\n"
            f"期望薪资 {detail['expected_salary_k']}K/月，预计 {detail['available_date']} 到岗。\n\n"
            f"备注：{note}\n\n"
            f"联系方式：{detail['phone']} ｜ {detail['email']}（已脱敏）"
        )
        if interview_note:
            turn.reply += f"\n\n面试记录摘要：{interview_note}"
        turn.facts.append(f"本次查询候选人：{detail['name']}（{detail['id']}）")
        turn.suggestions = ["安排这位候选人面试", "再推荐几位算法候选人"]

    # ------------------------------------------------------------------
    # 6. 面试安排（敏感）
    # ------------------------------------------------------------------
    def _handle_interview(self, turn: Turn) -> None:
        person = _extract_candidate(turn.message)
        moment = _extract_datetime(turn.message)
        if not person:
            turn.reply = "请告诉我要安排哪位候选人面试，例如：“安排王浩 2026-12-05 14:00 面试”。"
            turn.suggestions = ["帮我找会 Vue3 的前端候选人", "看看候选人的详细信息"]
            return
        if not moment:
            turn.reply = "请提供面试时间，例如：“安排王浩 2026-12-05 14:00 面试”。"
            turn.suggestions = ["安排王浩 2026-12-05 14:00 面试", "看看王浩的详细信息"]
            return
        started = time.perf_counter()
        # 敏感工具不会执行，只会抛出 SensitiveAction，由 run() 统一创建审批单。
        # 这里走 @tool 包装（而不是直接 toolbox），执行边界仍由 Toolbox 控制。
        self._invoke_lc_tool(
            turn,
            lc_schedule_interview,
            {
                "candidate": person["id"],
                "scheduled_at": moment.isoformat(timespec="seconds"),
            },
        )
        turn.step(
            "tool",
            "schedule_interview",
            "已请求创建面试日程",
            duration_ms=(time.perf_counter() - started) * 1000,
        )

    # ------------------------------------------------------------------
    # 7. 调薪（敏感）
    # ------------------------------------------------------------------
    def _handle_salary(self, turn: Turn) -> None:
        person = _extract_employee(turn.message)
        band_match = BAND_RE.search(turn.message)
        if not person:
            turn.reply = "请告诉我要调整哪位员工的薪资，例如：“把张伟的薪资调整到 P6-1”。"
            turn.suggestions = ["把张伟的薪资调整到 P6-1", "调薪需要哪些审批人？"]
            return
        if not band_match:
            turn.reply = "请提供目标薪资带宽，例如 P6-1（格式：职级-档位）。"
            turn.suggestions = ["把张伟的薪资调整到 P6-1", "调薪需要哪些审批人？"]
            return
        self._invoke_lc_tool(
            turn,
            lc_adjust_salary,
            {
                "employee": person["id"],
                "new_band": band_match.group().upper(),
                "reason": turn.message,
            },
        )

    # ------------------------------------------------------------------
    # 8. 入职
    # ------------------------------------------------------------------
    def _handle_onboarding(self, turn: Turn) -> None:
        person = _extract_candidate(turn.message)
        dates = _extract_dates(turn.message)
        if not person:
            turn.reply = "请告诉我要为哪位候选人办理入职，例如：“帮林晓办理入职，入职日期 2026-12-01”。"
            turn.suggestions = ["帮林晓办理入职，入职日期 2026-12-01", "看看林晓的详细信息"]
            return
        if not dates:
            turn.reply = "请提供入职日期（YYYY-MM-DD），我才能启动入职流程。"
            turn.suggestions = ["帮林晓办理入职，入职日期 2026-12-01", "看看林晓的详细信息"]
            return
        started = time.perf_counter()
        result = self._invoke_lc_tool(
            turn,
            lc_start_onboarding,
            {"candidate": person["id"], "start_date": dates[0]},
        )
        record = result["onboarding"]
        turn.tools_used.append("start_onboarding")
        turn.step(
            "tool",
            "start_onboarding",
            f"{record['id']} → 当前阶段：{record['stage']}",
            data={
                "onboarding_id": record["id"],
                "candidate_id": record["candidate_id"],
                "stage": record["stage"],
            },
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        todo = "；".join(step["name"] for step in record["steps"][:3])
        if result.get("replay"):
            headline = (
                f"该入职流程此前已经启动过（幂等重放，没有重复创建），"
                f"单号 **{record['id']}**，入职日期 {record['start_date']}。"
            )
        else:
            headline = (
                f"已为{record['candidate_name']}（{record['candidate_id']}）启动入职流程"
                f"（单号 **{record['id']}**，入职日期 {record['start_date']}）。"
            )
        turn.reply = (
            f"{headline}\n\n"
            f"当前阶段：{record['stage']}。\n"
            f"接下来会依次完成：{todo} 等共 {result['step_count']} 个步骤。\n\n"
            "每一步都有负责人和产出物，可在 HR 系统查看进度；任何一步失败我都会提示补做。"
        )
        turn.facts.append(f"已启动入职流程 {record['id']}")
        turn.suggestions = ["入职第一天要准备什么？", "查看入职流程进度"]

    # ------------------------------------------------------------------
    # 9. 工单
    # ------------------------------------------------------------------
    def _handle_ticket(self, turn: Turn) -> None:
        match = TICKET_RE.search(turn.message)
        ticket_id = match.group().upper() if match else None
        if not ticket_id:
            turn.reply = "请提供工单号（例如 T2026002），我再帮你查进展。"
            turn.suggestions = ["T2026002 这个工单进展如何？", "查一下我的年假余额"]
            return
        ticket, duration_ms = self._read_tool(
            turn,
            "get_ticket",
            {"ticket_id": ticket_id},
            lambda: self.toolbox.get_ticket(ticket_id, turn.actor),
        )
        self._format_ticket(turn, ticket, duration_ms)

    def _format_ticket(self, turn: Turn, ticket: dict, duration_ms: float) -> None:
        turn.tools_used.append("get_ticket")
        turn.step(
            "tool",
            "get_ticket",
            f"{ticket['id']} → {ticket['status_label']}",
            data={
                "ticket_id": ticket["id"],
                "status": ticket["status"],
                "priority": ticket["priority"],
            },
            duration_ms=duration_ms,
        )
        assignee = ticket.get("assignee_name") or ticket.get("assignee") or "待分配"
        turn.reply = (
            f"工单 **{ticket['id']}**《{ticket['title']}》当前状态：**{ticket['status_label']}**，"
            f"优先级 {ticket['priority']}，负责人 {assignee}，SLA {ticket['sla_hours']} 小时。\n\n"
            f"描述：{ticket['description']}\n\n"
            "如需催办，我可以帮你转给 HRBP 跟进。"
        )
        turn.facts.append(f"本次查询工单：{ticket['id']}")
        turn.suggestions = ["查一下其他工单", "工单处理 SLA 是多久？"]

    # ------------------------------------------------------------------
    # 10. 边界
    # ------------------------------------------------------------------
    def _handle_out_of_scope(self, turn: Turn) -> None:
        self._escalate_out_of_scope(turn, f"超出 HR 服务范围：{turn.message}")
