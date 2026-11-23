"""API request/response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    user_id: str
    role: str
    permissions: list[str]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    thread_id: str = "default"


class ChatResponse(BaseModel):
    answer: str
    route: str
    trace_id: str
    context: dict[str, Any] = Field(default_factory=dict)


class OrderItemRequest(BaseModel):
    product_id: str
    quantity: int = 1


class OrderCreateRequest(BaseModel):
    items: list[OrderItemRequest]


class RefundRequest(BaseModel):
    reason: str = "用户申请"


class FulfillmentRequest(BaseModel):
    order_id: str
    thread_id: str | None = None


class ApprovalRequest(BaseModel):
    thread_id: str
    approved: bool


# ---------- capability endpoints ----------
class PlanRequest(BaseModel):
    goal: str = Field(min_length=1)
    mode: str = "plan_solve"          # plan_solve | react
    thread_id: str = "default"


class HybridSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = 5
    mode: str = "hybrid"              # vector | bm25 | hybrid


class Text2SQLRequest(BaseModel):
    question: str = Field(min_length=1)


class SandboxRequest(BaseModel):
    code: str = Field(min_length=1)
    mode: str = "plain"               # plain | code_mode


class MemoryWriteRequest(BaseModel):
    thread_id: str = "default"
    user_input: str = ""
    assistant_output: str = ""
    preference: dict[str, Any] | None = None
    fact: dict[str, Any] | None = None


class EvalRequest(BaseModel):
    cases: list[dict[str, Any]] = Field(default_factory=list)
    runner: str = "echo"              # echo | agent
    baseline_pass_rate: float | None = None


class CitationRequest(BaseModel):
    answer: str = Field(min_length=1)
    chunks: list[dict[str, Any]] = Field(default_factory=list)


class GraphRAGRequest(BaseModel):
    query: str = Field(min_length=1)
    hops: int = 1


# ---------- frontier capability endpoints ----------
class GuardRequest(BaseModel):
    """安全检测通用请求：文本 + 可选不可信上下文。"""
    text: str = Field(min_length=1)
    untrusted: str | None = None
    role: str = "电商客服助手"
    allowed_tools: list[str] = Field(default_factory=list)


class ToolGuardRequest(BaseModel):
    """工具清单校验请求。"""
    tools: list[dict[str, Any]] = Field(default_factory=list)
    whitelist: list[str] | None = None


class PromptRequest(BaseModel):
    task: str = Field(min_length=1)
    max_iterations: int = 3
    score_threshold: float = 0.8


class OrchestrationRequest(BaseModel):
    pattern: str = "parallelization"
    task: str = Field(min_length=1)
    workers: list[str] = Field(default_factory=list)


class A2ADelegateRequest(BaseModel):
    agent: str = Field(min_length=1)
    task: str = Field(min_length=1)


class ToolRetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = 3
    use_rbac: bool = True


class ReasoningRequest(BaseModel):
    model: str = "gpt-4o"
    effort: str = "medium"
    max_cot_tokens: int | None = None


class TokenizeRequest(BaseModel):
    texts: list[str] = Field(default_factory=list)
    limit: int = 100


class StructuredRequest(BaseModel):
    text: str = Field(min_length=1)


class ModelSelectRequest(BaseModel):
    requirements: dict[str, Any] = Field(default_factory=dict)
    profiles: list[dict[str, Any]] = Field(default_factory=list)


class PromptTemplateRequest(BaseModel):
    name: str = Field(min_length=1)
    version: str = "v1"
    template: str = Field(min_length=1)
    variables: dict[str, Any] = Field(default_factory=dict)
    set_active: bool = False


class PromptRenderRequest(BaseModel):
    name: str = Field(min_length=1)
    version: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


class QueryRewriteRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: str = "multi"              # multi | hyde | stepback | decompose


class RagasRequest(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    contexts: list[Any] = Field(default_factory=list)
    ground_truth: str | None = None


class AdvancedRAGRequest(BaseModel):
    question: str = Field(min_length=1)
    mode: str = "corrective"          # corrective | self_rag | agentic


class ACLRetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    tenant: str | None = None


class ExtractionRequest(BaseModel):
    text: str = Field(min_length=1)


class FeatureFlagRequest(BaseModel):
    name: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    enabled: bool = True
    ratio: float = 0.5
    variants: list[str] = Field(default_factory=list)


class HealthCheckRequest(BaseModel):
    snapshot: dict[str, Any] = Field(default_factory=dict)


class JudgeRequest(BaseModel):
    answer: str = Field(min_length=1)
    rubric: str = "评估答案的准确性、完整性与相关性，0-100 分"
    expected: str | None = None
    human_score: float | None = None


class TrajectoryRequest(BaseModel):
    trace: Any = None
    expected: list[str] = Field(default_factory=list)


class AttributionRequest(BaseModel):
    case: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)
    trace: Any = None
    promote: bool = False


class ExperimentRequest(BaseModel):
    name: str = "ab-test"
    user_id: str = Field(min_length=1)
    control_scores: list[float] = Field(default_factory=list)
    treatment_scores: list[float] = Field(default_factory=list)
    treatment_ratio: float = 0.5
