/** 会话、消息、审批、SSE 事件与前端消息模型 */

export const AGENT_TYPES = ['SUPERVISOR', 'SHOPPING', 'SERVICE', 'OPS'] as const
export type AgentType = (typeof AGENT_TYPES)[number]

export const RISK_LEVELS = ['READ', 'WRITE', 'IRREVERSIBLE'] as const
export type RiskLevel = (typeof RISK_LEVELS)[number]

export const MESSAGE_ROLES = ['user', 'assistant', 'system', 'tool'] as const
export type MessageRole = (typeof MESSAGE_ROLES)[number]

export const APPROVAL_STATUSES = ['PENDING', 'APPROVED', 'REJECTED', 'EXPIRED'] as const
export type ApprovalStatus = (typeof APPROVAL_STATUSES)[number]
export type ApprovalDecision = 'APPROVE' | 'REJECT'

export const FINISH_REASONS = ['stop', 'interrupted', 'approval_required', 'max_steps', 'error'] as const
export type FinishReason = (typeof FINISH_REASONS)[number]

/* ------------------------------ VO ------------------------------ */

export interface SessionVO {
  id: number
  title: string
  agentType: AgentType
  status: string
  lastMessageAt: string | null
  createdAt: string
}

export interface ToolCallVO {
  callId: string
  name: string
  args?: Record<string, unknown>
  ok?: boolean
  summary?: string
  risk?: RiskLevel
  latencyMs?: number
}

export interface CitationVO {
  docId: number
  chunkId: number
  title: string
  snippet: string
  score: number
}

export interface ApprovalVO {
  id: number
  sessionId: number
  actionType: string
  title: string
  detail: Record<string, unknown>
  risk: RiskLevel
  status: ApprovalStatus
  createdAt: string
  expiresAt: string
}

export interface MessageVO {
  id: number
  role: MessageRole
  content: string
  agentType?: AgentType
  toolCalls?: ToolCallVO[]
  citations?: CitationVO[]
  tokenIn?: number
  tokenOut?: number
  costCents?: number
  createdAt: string
}

export interface ChatStreamRequest {
  sessionId: number
  message: string
  clientMsgId?: string
}

export interface ApprovalDecisionRequest {
  decision: ApprovalDecision
  comment?: string
}

export interface ApprovalDecisionResult {
  id: number
  status: ApprovalStatus
  result?: Record<string, unknown>
}

/** 审批卡片提交载荷 */
export interface ApprovalDecisionPayload {
  approvalId: number
  decision: ApprovalDecision
  comment: string
}

export interface InterruptResult {
  interrupted: boolean
}

/* ------------------------------ SSE 事件 ------------------------------ */

export interface MetaEventData {
  traceId: string
  messageId: number
  sessionId: number
}

export interface AgentEventData {
  agentType: AgentType
  reason?: string
}

export interface DeltaEventData {
  text: string
}

export interface ToolCallEventData {
  callId: string
  name: string
  args: Record<string, unknown>
  risk: RiskLevel
}

export interface ToolResultEventData {
  callId: string
  name: string
  ok: boolean
  summary?: string
  latencyMs?: number
}

export interface CitationEventData {
  docId: number
  chunkId: number
  title: string
  snippet: string
  score: number
}

export interface ApprovalEventData {
  approvalId: number
  title: string
  detail: Record<string, unknown>
  risk: RiskLevel
  expiresAt: string
}

export interface UsageEventData {
  promptTokens: number
  completionTokens: number
  costCents: number
  model?: string
}

export interface DoneEventData {
  messageId: number
  finishReason: FinishReason
}

export interface ErrorEventData {
  code: number
  message: string
}

/* ------------------------------ UI 模型 ------------------------------ */

export type ToolCallStatus = 'running' | 'ok' | 'failed'

export interface ChatToolCall {
  callId: string
  name: string
  args: Record<string, unknown>
  risk: RiskLevel
  status: ToolCallStatus
  ok?: boolean
  summary?: string
  latencyMs?: number
}

export interface ChatApproval {
  approvalId: number
  title: string
  detail: Record<string, unknown>
  risk: RiskLevel
  status: ApprovalStatus
  createdAt: string
  expiresAt: string
  sessionId?: number
  actionType?: string
  result?: Record<string, unknown>
}

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  agentType?: AgentType
  toolCalls: ChatToolCall[]
  citations: CitationVO[]
  approvals: ChatApproval[]
  streaming: boolean
  interrupted?: boolean
  error?: string
  tokenIn?: number
  tokenOut?: number
  costCents?: number
  createdAt?: string
  traceId?: string
}
