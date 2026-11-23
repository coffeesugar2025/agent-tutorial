import type {
  AgentType,
  ApprovalEventData,
  ChatApproval,
  ChatMessage,
  ChatToolCall,
  CitationVO,
  MessageVO,
  ToolCallVO,
  ToolResultEventData,
} from '@/types'
import { uid } from './guard'

export function createUserMessage(content: string): ChatMessage {
  return {
    id: uid('user'),
    role: 'user',
    content,
    toolCalls: [],
    citations: [],
    approvals: [],
    streaming: false,
    createdAt: new Date().toISOString(),
  }
}

export function createAssistantDraft(agentType: AgentType = 'SUPERVISOR'): ChatMessage {
  return {
    id: uid('assistant'),
    role: 'assistant',
    content: '',
    agentType,
    toolCalls: [],
    citations: [],
    approvals: [],
    streaming: true,
    createdAt: new Date().toISOString(),
  }
}

export function mapToolCall(vo: ToolCallVO): ChatToolCall {
  const failed = vo.ok === false
  return {
    callId: vo.callId,
    name: vo.name,
    args: vo.args ?? {},
    risk: vo.risk ?? 'READ',
    status: vo.ok === undefined ? 'running' : failed ? 'failed' : 'ok',
    ok: vo.ok,
    summary: vo.summary,
    latencyMs: vo.latencyMs,
  }
}

export function mapCitations(list?: CitationVO[]): CitationVO[] {
  if (!Array.isArray(list)) return []
  return list.filter((item) => item && typeof item.chunkId === 'number' && typeof item.docId === 'number')
}

export function mapMessageVO(vo: MessageVO): ChatMessage {
  return {
    id: `srv-${vo.id}`,
    role: vo.role,
    content: vo.content ?? '',
    agentType: vo.agentType,
    toolCalls: (vo.toolCalls ?? []).map(mapToolCall),
    citations: mapCitations(vo.citations),
    approvals: [],
    streaming: false,
    tokenIn: vo.tokenIn,
    tokenOut: vo.tokenOut,
    costCents: vo.costCents,
    createdAt: vo.createdAt,
  }
}

export function approvalFromEvent(data: ApprovalEventData, sessionId?: number): ChatApproval {
  return {
    approvalId: data.approvalId,
    title: data.title || '待审批操作',
    detail: data.detail,
    risk: data.risk,
    status: 'PENDING',
    createdAt: new Date().toISOString(),
    expiresAt: data.expiresAt,
    sessionId,
  }
}

/** 把 tool_result 合并进对应的 tool_call 卡片；找不到则补一条 */
export function applyToolResult(calls: ChatToolCall[], data: ToolResultEventData): void {
  const target = calls.find((item) => item.callId === data.callId)
  if (target) {
    target.status = data.ok ? 'ok' : 'failed'
    target.ok = data.ok
    target.summary = data.summary
    target.latencyMs = data.latencyMs
    return
  }
  calls.push({
    callId: data.callId,
    name: data.name,
    args: {},
    risk: 'READ',
    status: data.ok ? 'ok' : 'failed',
    ok: data.ok,
    summary: data.summary,
    latencyMs: data.latencyMs,
  })
}

export function appendCitation(list: CitationVO[], citation: CitationVO): void {
  const exists = list.some((item) => item.docId === citation.docId && item.chunkId === citation.chunkId)
  if (!exists) list.push(citation)
}
