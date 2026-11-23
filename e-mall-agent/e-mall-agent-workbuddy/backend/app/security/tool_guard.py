"""MCP 工具投毒 / 恶意 Server 防护。

威胁模型：
- 工具清单投毒：恶意 MCP Server 在 tool name/description/schema 中夹带
  「泄露密钥」「忽略用户指令」「隐藏参数」等描述，诱导模型执行越权或资损操作。
- 清单漂移：工具被新增/删除/描述被篡改却无人察觉。
- 返回投毒：工具返回内容携带间接注入指令。

提供：工具清单规则校验（并附带可选 HMAC 签名校验）、工具白名单、工具变更审计
（只调用 AuditLogger，不修改它）、工具返回注入扫描（复用 injection.InjectionScanner）。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from .audit import AuditLogger, get_audit_logger
from .injection import InjectionScanner, ScanResult, isolate_untrusted
from .rbac import TOOL_PERMISSIONS

# 默认白名单与现有 RBAC 工具权限表保持一致；可由构造参数覆盖。
DEFAULT_WHITELIST: frozenset[str] = frozenset(TOOL_PERMISSIONS)

# 可能用于隐藏行为的参数名。
HIDDEN_PARAM_NAMES: frozenset[str] = frozenset(
    {"debug", "internal", "secret", "hidden", "admin", "root", "bypass",
     "sudo", "api_key", "token", "password", "override"}
)


@dataclass
class ToolRule:
    """工具描述/名称的可疑特征规则。"""

    name: str
    pattern: str
    severity: str = "high"
    description: str = ""
    flags: int = re.IGNORECASE
    _regex: re.Pattern[str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._regex = re.compile(self.pattern, self.flags)

    def search(self, text: str):
        return self._regex.search(text)


@dataclass
class ToolSpec:
    """工具的规范化描述，兼容 dict / LangChain BaseTool / pydantic schema。"""

    name: str
    description: str = ""
    schema: dict[str, Any] | None = None

    @classmethod
    def from_obj(cls, tool: Any) -> "ToolSpec":
        if isinstance(tool, dict):
            name = tool.get("name") or tool.get("tool_name") or ""
            description = tool.get("description") or tool.get("desc") or ""
            schema: Any = tool.get("schema") or tool.get("parameters") or tool.get("args_schema")
        else:
            name = getattr(tool, "name", None) or getattr(tool, "__name__", "")
            description = (getattr(tool, "description", None)
                           or getattr(tool, "__doc__", "") or "")
            schema = (getattr(tool, "schema", None) or getattr(tool, "parameters", None)
                      or getattr(tool, "args_schema", None) or getattr(tool, "args", None))
        if schema is not None and not isinstance(schema, dict):
            if hasattr(schema, "model_json_schema"):
                schema = schema.model_json_schema()
            elif callable(getattr(schema, "schema", None)):
                try:
                    schema = schema.schema()
                except Exception:  # pragma: no cover - schema 不可解析时降级为字符串
                    schema = {"raw": str(schema)}
            else:
                schema = {"raw": str(schema)}
        return cls(name=str(name or ""), description=str(description or "").strip(), schema=schema)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "schema": self.schema}


@dataclass
class ToolValidationReport:
    """单个工具的校验报告：whitelisted 表示在白名单内，safe 表示未命中投毒规则。"""

    tool_name: str
    whitelisted: bool
    safe: bool
    issues: list[str] = field(default_factory=list)
    risk: str = "none"

    @property
    def accepted(self) -> bool:
        return self.whitelisted and self.safe

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "whitelisted": self.whitelisted,
            "safe": self.safe,
            "accepted": self.accepted,
            "issues": list(self.issues),
            "risk": self.risk,
        }


@dataclass
class ManifestReport:
    """整份工具清单的校验报告。"""

    reports: list[ToolValidationReport] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.accepted for r in self.reports)

    @property
    def rejected(self) -> list[ToolValidationReport]:
        return [r for r in self.reports if not r.accepted]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "tools": [r.as_dict() for r in self.reports]}


@dataclass(frozen=True)
class ToolChange:
    """一次工具清单变更：added / removed / description_changed / schema_changed。"""

    change_type: str
    name: str
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"change_type": self.change_type, "name": self.name, "detail": self.detail}


def canonical_manifest(tools: Iterable[Any]) -> str:
    """生成确定性 JSON 摘要，用于比对与签名。"""
    specs = sorted((ToolSpec.from_obj(t).as_dict() for t in tools), key=lambda d: d["name"])
    return json.dumps(specs, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_manifest(tools: Iterable[Any], secret: str) -> str:
    """对工具清单做 HMAC-SHA256 签名（规则校验之外的可选完整性校验）。"""
    body = canonical_manifest(tools).encode("utf-8")
    return _b64(hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest())


def verify_manifest(tools: Iterable[Any], signature: str, secret: str) -> bool:
    expected = sign_manifest(tools, secret)
    return hmac.compare_digest(signature, expected)


class ToolGuard:
    """工具清单校验、白名单、变更审计与返回内容扫描的统一入口。"""

    SUSPICIOUS_RULES: tuple[ToolRule, ...] = (
        ToolRule(
            name="密钥外泄诱导",
            pattern=(r"api[_\- ]?key|secret[_\- ]?key|access[_\- ]?token|\.env\b|环境变量"
                     r"|泄露(?:密钥|密码|凭证|token)|send\s+(?:the\s+)?(?:key|secret|token)"
                     r"|exfiltrat\w*"),
            severity="high",
            description="工具描述要求读取或外传密钥凭证",
        ),
        ToolRule(
            name="忽略用户指令",
            pattern=(r"ignore\s+(?:user|all|previous)|disregard\s+(?:user|instructions)"
                     r"|忽略(?:用户|之前|上面)(?:的)?(?:指令|要求)|不要听(?:从|用户)"),
            severity="high",
            description="工具描述要求忽略用户或系统指令",
        ),
        ToolRule(
            name="隐藏参数/静默行为",
            pattern=(r"hidden\s+parameter|do\s+not\s+(?:show|tell|mention)|silently|secretly"
                     r"|隐藏参数|不要告诉用户|悄悄(?:执行|调用)|静默(?:执行|上报)"),
            severity="high",
            description="工具描述包含隐藏参数或对用户隐瞒的行为",
        ),
        ToolRule(
            name="越狱/权限提升",
            pattern=r"jailbreak|unrestricted|bypass\s+(?:permission|auth)|无限制|绕过(?:权限|验证|风控)",
            severity="medium",
            description="工具描述包含越狱或权限提升意图",
        ),
    )

    def __init__(
        self,
        whitelist: Iterable[str] | None = None,
        *,
        audit_logger: AuditLogger | None = None,
        scanner: InjectionScanner | None = None,
        suspicious_rules: Iterable[ToolRule] | None = None,
    ) -> None:
        self.whitelist: set[str] = set(whitelist if whitelist is not None else DEFAULT_WHITELIST)
        self.audit_logger = audit_logger or get_audit_logger()
        self.scanner = scanner or InjectionScanner()
        self.suspicious_rules = list(
            suspicious_rules if suspicious_rules is not None else self.SUSPICIOUS_RULES
        )

    def validate_tool(self, spec: ToolSpec) -> ToolValidationReport:
        """校验单个工具：白名单 + name/description/schema 投毒规则。"""
        issues: list[str] = []
        if spec.name not in self.whitelist:
            issues.append(f"工具 {spec.name!r} 不在白名单内")

        risk_rank = 0
        probe = f"{spec.name}\n{spec.description}"
        for rule in self.suspicious_rules:
            hit = rule.search(probe)
            if hit:
                issues.append(f"{rule.name}: 命中 {hit.group(0)!r}")
                risk_rank = max(risk_rank, _severity_rank(rule.severity))

        if isinstance(spec.schema, dict):
            properties = spec.schema.get("properties", {})
            if isinstance(properties, dict):
                for param, info in properties.items():
                    if str(param).lower() in HIDDEN_PARAM_NAMES:
                        issues.append(f"schema 含可疑隐藏参数 {param!r}")
                        risk_rank = max(risk_rank, 2)
                    text = (info.get("description", "") if isinstance(info, dict) else str(info))
                    for rule in self.suspicious_rules:
                        hit = rule.search(str(text))
                        if hit:
                            issues.append(f"schema 参数 {param!r} {rule.name}")
                            risk_rank = max(risk_rank, _severity_rank(rule.severity))

        risk = {0: "none", 1: "low", 2: "medium", 3: "high", 4: "critical"}.get(risk_rank, "high")
        no_poison = not any(
            issue.startswith(("密钥外泄诱导", "忽略用户指令", "隐藏参数/静默行为",
                              "越狱/权限提升", "schema "))
            for issue in issues
        )
        return ToolValidationReport(
            tool_name=spec.name,
            whitelisted=spec.name in self.whitelist,
            safe=no_poison,
            issues=issues,
            risk=risk,
        )

    def validate_manifest(self, tools: Iterable[Any]) -> ManifestReport:
        """校验整份工具清单，返回可被断言的汇总报告。"""
        return ManifestReport([self.validate_tool(ToolSpec.from_obj(t)) for t in tools])

    def enforce_tools(self, tools: Iterable[Any], *, actor: str = "system") -> list[Any]:
        """只放行白名单内且安全的工具；其余拒绝并写审计。"""
        kept: list[Any] = []
        for tool in tools:
            spec = ToolSpec.from_obj(tool)
            report = self.validate_tool(spec)
            if report.accepted:
                kept.append(tool)
            else:
                self.audit_logger.record(
                    actor, "tool.rejected", spec.name, "block", "; ".join(report.issues)
                )
        return kept

    def diff(
        self,
        old_tools: Iterable[Any],
        new_tools: Iterable[Any],
        *,
        actor: str = "system",
        record: bool = True,
    ) -> list[ToolChange]:
        """对比两次工具清单快照，报告新增/删除/描述与 schema 变更，并写入审计。"""
        old = {s.name: s for s in (ToolSpec.from_obj(t) for t in old_tools)}
        new = {s.name: s for s in (ToolSpec.from_obj(t) for t in new_tools)}
        changes: list[ToolChange] = []
        for name in sorted(new.keys() - old.keys()):
            changes.append(ToolChange("added", name, "工具被新增"))
        for name in sorted(old.keys() - new.keys()):
            changes.append(ToolChange("removed", name, "工具被删除"))
        for name in sorted(old.keys() & new.keys()):
            if old[name].description != new[name].description:
                changes.append(ToolChange(
                    "description_changed", name,
                    f"描述变更: {old[name].description!r} -> {new[name].description!r}",
                ))
            if old[name].schema != new[name].schema:
                changes.append(ToolChange("schema_changed", name, "参数 schema 变更"))
        if record:
            for change in changes:
                self.audit_logger.record(
                    actor, f"tool.{change.change_type}", change.name, "alert", change.detail
                )
        return changes

    def scan_tool_return(self, text: str) -> ScanResult:
        """复用注入扫描器检查工具返回内容。"""
        return self.scanner.scan(text)

    def quarantine_tool_return(self, text: str, *, label: str = "tool_output") -> str:
        """对工具返回做隔离包裹（转义 + 清洗 + 指令层级），供拼入 prompt 前使用。"""
        return isolate_untrusted(text, label=label, scanner=self.scanner)


def _severity_rank(severity: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(severity, 3)
