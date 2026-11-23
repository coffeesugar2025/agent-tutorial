"""Plan-and-Solve 规划器。

使用 LangChain ``ChatPromptTemplate`` + ``PydanticOutputParser`` 组成 LCEL
管道，把复杂用户目标拆成结构化的 ``Plan``。默认使用离线规则输出结构化
JSON，保证零 API Key 也能确定性运行；也可注入真实 ``BaseChatModel``。
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import BaseTool

from .common import extract_steps
from .models import Plan, PlanOutput, PlanStep


class PlanAndSolvePlanner:
    """结构化任务规划器。

    Args:
        llm: 可选的语言模型。为 None 时使用内置离线规则生成结构化输出。
        tools: 可选的工具列表，仅用于向 prompt 提供可用工具信息。
    """

    def __init__(
        self,
        llm: BaseChatModel | None = None,
        tools: list[BaseTool] | None = None,
    ) -> None:
        self._llm = llm
        self.tools = list(tools or [])
        self._parser = PydanticOutputParser(pydantic_object=PlanOutput)
        self._prompt = ChatPromptTemplate.from_messages([
            ("system", "你是任务规划器。把用户目标拆成有序、可执行的步骤。\n"
                       "{format_instructions}"),
            ("human", "用户目标：{goal}"),
        ]).partial(format_instructions=self._parser.get_format_instructions())

    def _rule_structured_output(self, prompt_value: Any) -> str:
        """从 prompt 中提取目标，用规则生成结构化 JSON 字符串。

        Args:
            prompt_value: ``ChatPromptTemplate`` 产出的提示值。

        Returns:
            符合 ``PlanOutput`` 结构的 JSON 字符串。
        """
        goal = ""
        for message in prompt_value.messages:
            if isinstance(message, HumanMessage):
                goal = str(message.content)
                break
        steps = extract_steps(goal)
        return json.dumps(
            {"steps": [step.model_dump() for step in steps]}, ensure_ascii=False
        )

    @property
    def chain(self) -> Runnable[dict[str, Any], PlanOutput]:
        """返回 ``prompt | model | parser`` 的 LCEL 管道。"""
        model: Runnable[Any, Any] = (
            self._llm if self._llm is not None
            else RunnableLambda(self._rule_structured_output)
        )
        return self._prompt | model | self._parser

    @staticmethod
    def _ensure_dependencies(steps: list[PlanStep]) -> list[PlanStep]:
        """为缺失依赖的步骤补齐线性依赖链。"""
        result: list[PlanStep] = []
        for index, step in enumerate(steps):
            if index == 0:
                step.depends_on = []
            elif not step.depends_on:
                step.depends_on = [result[-1].id]
            result.append(step)
        return result

    def plan(self, goal: str, user: Any = None) -> Plan:
        """把用户目标拆成结构化计划。

        Args:
            goal: 用户目标文本。
            user: 可选用户对象，保留用于扩展个性化规划。

        Returns:
            含有序步骤与依赖关系的 ``Plan``。
        """
        output: PlanOutput = self.chain.invoke({"goal": goal})
        steps = self._ensure_dependencies(output.steps)
        return Plan(goal=goal, steps=steps)

    async def aplan(self, goal: str, user: Any = None) -> Plan:
        """``plan`` 的异步版本。"""
        output: PlanOutput = await self.chain.ainvoke({"goal": goal})
        steps = self._ensure_dependencies(output.steps)
        return Plan(goal=goal, steps=steps)
