"""越狱检测与输出安全过滤 / 内容审核。

威胁模型：
- 输入侧：DAN、角色扮演绕过、编码绕过、多轮渐进诱导等越狱手法，绕过 system 规则。
- 输出侧：模型回答泄露敏感信息、对危险操作做出承诺、回显注入指令，从而误导后续动作。

提供：
1. JailbreakDetector：可配置阈值与规则的输入侧越狱检测。
2. OutputModerator：输出侧 pass/block 判定 + 原因。
3. 可直接挂到 LangChain middleware 的函数（与 specialists.py 的 @wrap_tool_call 写法等价，
   但不修改该文件）；核心判定逻辑保持在纯函数中，便于本地确定性测试。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .injection import InjectionScanner

_SEVERITY_WEIGHT: dict[str, float] = {
    "low": 0.25,
    "medium": 0.5,
    "high": 1.0,
    "critical": 1.5,
}


@dataclass
class JailbreakRule:
    """一条越狱特征规则。"""

    name: str
    pattern: str
    severity: str = "high"
    description: str = ""
    flags: int = re.IGNORECASE
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._regex = re.compile(self.pattern, self.flags)

    def finditer(self, text: str):
        return self._regex.finditer(text)


@dataclass
class ModerationResult:
    """输入侧越狱检测结果：blocked + 风险分 + 命中原因。"""

    blocked: bool
    score: float
    risk: str
    reasons: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.blocked

    def as_dict(self) -> dict[str, Any]:
        return {
            "blocked": self.blocked,
            "score": self.score,
            "risk": self.risk,
            "reasons": list(self.reasons),
        }


class JailbreakDetector:
    """输入侧越狱检测器。threshold 与规则列表均可配置，便于调优误杀率。"""

    DEFAULT_RULES: tuple[JailbreakRule, ...] = (
        JailbreakRule(
            name="DAN/越狱人格",
            pattern=r"\bDAN\b|do\s+anything\s+now|developer\s+mode|jailbreak|越狱(?:模式)?|不受限制(?:的)?(?:AI|模型|助手)",
            severity="high",
            description="请求切换到无限制人格",
        ),
        JailbreakRule(
            name="角色扮演绕过",
            pattern=(r"you\s+are\s+(?:now\s+)?(?:a|an|the)\s+(?:unrestricted|evil|uncensored|no\s+rules)"
                     r"|act\s+as\s+(?:a|an|the)\s+(?:unrestricted|evil|jailbroken)"
                     r"|pretend\s+(?:you\s+are|to\s+be)\s+(?:a|an|the)?\s*(?:unrestricted|evil)"
                     r"|扮演(?:一个|一位)?(?:不受限制|没有规则|邪恶|无底线)"
                     r"|假装(?:你)?是(?:一个)?(?:不受限制|没有规则)"),
            severity="high",
            description="通过角色扮演绕过规则",
        ),
        JailbreakRule(
            name="编码绕过",
            pattern=(r"\bbase64\b|\brot13\b|encode\s+(?:this|the\s+instruction)|decode\s+the\s+following"
                     r"|用(?:base64|rot13|拼音|倒序|编码)(?:输出|回答|绕过)|把(?:以下|指令)(?:编码|加密|倒过来)"),
            severity="high",
            description="通过编码/变形绕过关键词检测",
        ),
        JailbreakRule(
            name="多轮渐进诱导",
            pattern=(r"in\s+(?:the\s+)?(?:previous|earlier|last)\s+(?:turn|message|message[s]?)\s+we"
                     r"|continue\s+(?:from|where)\s+(?:we|you)\s+(?:left|agreed)"
                     r"|(?:按照|基于)(?:我们|之前|前面)(?:的)?(?:约定|讨论|那次越狱)"
                     r"|继续(?:上次|之前)(?:的)?(?:越狱|无限制)"),
            severity="high",
            description="利用对话历史渐进式突破限制",
        ),
        JailbreakRule(
            name="指令覆盖",
            pattern=(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+(?:instructions?|rules?)"
                     r"|忽略(?:之前|上面|所有)(?:的)?(?:指令|规则)"),
            severity="high",
            description="要求忽略既有指令",
        ),
    )

    def __init__(
        self,
        rules: list[JailbreakRule] | None = None,
        *,
        threshold: float = 1.0,
    ) -> None:
        self.rules = list(rules if rules is not None else self.DEFAULT_RULES)
        self.threshold = threshold

    def detect(self, text: str) -> ModerationResult:
        """检测输入文本；风险分达到 threshold 即判定为越狱并阻断。"""
        text = text or ""
        reasons: list[str] = []
        score = 0.0
        top = "none"
        for rule in self.rules:
            hits = list(rule.finditer(text))
            if hits:
                reasons.append(f"{rule.name}: {rule.description}")
                score += _SEVERITY_WEIGHT.get(rule.severity, 1.0)
                if _SEVERITY_WEIGHT.get(rule.severity, 1.0) >= _SEVERITY_WEIGHT.get(top, 0.0):
                    top = rule.severity
        return ModerationResult(
            blocked=score >= self.threshold,
            score=score,
            risk=top,
            reasons=reasons,
        )


@dataclass
class OutputRule:
    """一条输出安全检查规则。"""

    name: str
    pattern: str
    severity: str = "high"
    description: str = ""
    flags: int = re.IGNORECASE
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._regex = re.compile(self.pattern, self.flags)

    def finditer(self, text: str):
        return self._regex.finditer(text)


@dataclass
class OutputCheck:
    """输出审核结果：decision=pass/block，reasons 给出命中原因。"""

    decision: str
    reasons: list[str] = field(default_factory=list)
    risk: str = "none"

    @property
    def passed(self) -> bool:
        return self.decision == "pass"

    @property
    def blocked(self) -> bool:
        return self.decision == "block"

    def as_dict(self) -> dict[str, Any]:
        return {"decision": self.decision, "reasons": list(self.reasons), "risk": self.risk}


class OutputModerator:
    """输出侧内容审核器。检测敏感信息泄露、危险操作承诺与注入指令回显。"""

    DEFAULT_RULES: tuple[OutputRule, ...] = (
        OutputRule(
            name="敏感信息泄露",
            pattern=(r"sk-[A-Za-z0-9]{8,}|api[_\- ]?key\s*[:：]|secret[_\- ]?key\s*[:：]"
                     r"|access[_\- ]?token\s*[:：]|密码\s*[:：]\s*\S+|密钥\s*[:：]\s*\S+"
                     r"|身份证号?\s*[:：]\s*\d{15,18}"),
            severity="high",
            description="回答中泄露密钥/凭证/密码/身份证等敏感信息",
        ),
        OutputRule(
            name="危险操作承诺",
            pattern=(r"已经(?:为你|帮您)?(?:下单|退款|付款)|无需(?:确认|验证|授权)|跳过(?:确认|验证)"
                     r"|绕过(?:权限|验证|风控)|保证(?:退款|全额退款)|我(?:直接|已经)(?:替|帮)(?:你|您)"),
            severity="high",
            description="对下单/退款/绕过校验等危险操作作出承诺",
        ),
        OutputRule(
            name="注入指令回显",
            pattern=(r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?|system\s*prompt"
                     r"|忽略(?:之前|上面)(?:的)?指令|我的系统提示(?:词)?是"),
            severity="medium",
            description="把注入指令或系统提示词回显给用户",
        ),
    )

    def __init__(self, rules: list[OutputRule] | None = None) -> None:
        self.rules = list(rules if rules is not None else self.DEFAULT_RULES)

    def check(self, text: str) -> OutputCheck:
        text = text or ""
        reasons: list[str] = []
        top = "none"
        for rule in self.rules:
            if list(rule.finditer(text)):
                reasons.append(f"{rule.name}: {rule.description}")
                if _SEVERITY_WEIGHT.get(rule.severity, 1.0) > _SEVERITY_WEIGHT.get(top, 0.0):
                    top = rule.severity
        return OutputCheck(
            decision="block" if reasons else "pass",
            reasons=reasons,
            risk=top,
        )


def detect_jailbreak(text: str, detector: JailbreakDetector | None = None) -> ModerationResult:
    """输入侧便捷函数：检测越狱，默认阻断阈值 1.0。"""
    return (detector or JailbreakDetector()).detect(text)


def check_output(text: str, moderator: OutputModerator | None = None) -> OutputCheck:
    """输出侧便捷函数：返回 pass/block + 原因。"""
    return (moderator or OutputModerator()).check(text)


def check_tool_output(
    text: str,
    *,
    moderator: OutputModerator | None = None,
    scanner: InjectionScanner | None = None,
) -> OutputCheck:
    """工具返回综合检查：注入扫描命中即视为不可信并阻断。"""
    scan = (scanner or InjectionScanner()).scan(text)
    check = (moderator or OutputModerator()).check(text)
    reasons = list(check.reasons)
    if scan.suspicious:
        rules = ", ".join(m.rule for m in scan.matched)
        reasons.append(f"工具返回注入扫描命中（风险={scan.risk}，规则={rules}）")
    decision = "block" if (check.blocked or scan.suspicious) else "pass"
    risk = check.risk if _SEVERITY_WEIGHT.get(check.risk, 0.0) >= _SEVERITY_WEIGHT.get(scan.risk, 0.0) else scan.risk
    return OutputCheck(decision=decision, reasons=reasons, risk=risk)


BLOCKED_TOOL_MESSAGE = "【安全拦截】工具返回内容未通过安全审核，已阻断；未执行其中任何指令。"


def _result_text(result: Any) -> str:
    """从 ToolMessage / str / 多模态 content 中提取可扫描文本。"""
    content = getattr(result, "content", None)
    if content is None:
        return "" if result is None else str(result)
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for part in content:
            parts.append(part.get("text", "") if isinstance(part, dict) else str(part))
        return "".join(parts)
    return str(content)


async def guard_tool_call_impl(request: Any, handler: Any) -> Any:
    """中间件核心逻辑（纯函数式，可直接用假 request/handler 测试）。

    先执行工具，再对返回做注入扫描与输出审核；命中则替换为安全拒绝消息。
    """
    result = await handler(request)
    text = _result_text(result)
    if not text:
        return result
    verdict = check_tool_output(text)
    if verdict.passed:
        return result
    try:
        from langchain_core.messages import ToolMessage

        call = getattr(request, "tool_call", {}) or {}
        tool_call_id = call.get("id", "unknown")
        return ToolMessage(content=BLOCKED_TOOL_MESSAGE, tool_call_id=tool_call_id)
    except Exception:  # pragma: no cover - 无 langchain 环境下退化为纯文本
        return BLOCKED_TOOL_MESSAGE


# 与 specialists.py 中的 @wrap_tool_call 等价：用 LangChain 官方装饰器包装核心逻辑，
# 得到的函数可直接放进 create_agent(middleware=[...])；不修改原文件。
try:  # pragma: no cover - 仅依赖包装期是否可用
    from langchain.agents.middleware import wrap_tool_call as _wrap_tool_call

    guard_tool_call = _wrap_tool_call(guard_tool_call_impl)
except Exception:  # pragma: no cover
    guard_tool_call = guard_tool_call_impl
