/**
 * SSE 协议解析（纯函数，无网络依赖，便于单测）。
 * 事件块以空行分隔；`event:` + 一行或多行 `data:`；`: ping` 注释行忽略。
 */
import type {
  AgentEventData,
  AgentType,
  ApprovalEventData,
  CitationVO,
  DoneEventData,
  ErrorEventData,
  FinishReason,
  MetaEventData,
  RiskLevel,
  ToolCallEventData,
  ToolResultEventData,
  UsageEventData,
} from '@/types'
import {
  isRecord,
  pickBoolean,
  pickNumber,
  pickOptionalString,
  pickRecord,
  pickString,
} from '@/utils/guard'

export type StreamCloseReason = 'done' | 'approval_required' | 'error' | 'aborted' | 'closed'

export interface StreamHandlers {
  onOpen?: () => void
  onMeta?: (data: MetaEventData) => void
  onAgent?: (data: AgentEventData) => void
  onDelta?: (data: { text: string }) => void
  onToolCall?: (data: ToolCallEventData) => void
  onToolResult?: (data: ToolResultEventData) => void
  onCitation?: (data: CitationVO) => void
  onApproval?: (data: ApprovalEventData) => void
  onUsage?: (data: UsageEventData) => void
  onDone?: (data: DoneEventData) => void
  onError?: (data: ErrorEventData) => void
  onUnknownEvent?: (event: string, data: unknown) => void
  onClose?: (reason: StreamCloseReason) => void
}

export interface SseFrame {
  event: string
  data: string
  id?: string
}

/** 解析单个事件块；纯注释块（`: ping`）返回 null */
export function parseSseBlock(block: string): SseFrame | null {
  const lines = block.split('\n')
  const dataLines: string[] = []
  let event = ''
  let id = ''
  let hasField = false

  for (const rawLine of lines) {
    const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
    if (!line || line.startsWith(':')) continue // 心跳 / 空行
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)

    if (field === 'event') {
      event = value
      hasField = true
    } else if (field === 'data') {
      dataLines.push(value)
      hasField = true
    } else if (field === 'id') {
      id = value
    }
    // retry 与未知字段按 SSE 规范忽略
  }

  if (!hasField) return null
  const data = dataLines.join('\n')
  if (!event && !data) return null
  return { event: event || 'message', data, id: id || undefined }
}

function asAgentType(value: string): AgentType {
  return value === 'SHOPPING' || value === 'SERVICE' || value === 'OPS' || value === 'SUPERVISOR'
    ? value
    : 'SUPERVISOR'
}

function asRisk(value: string): RiskLevel {
  return value === 'WRITE' || value === 'IRREVERSIBLE' ? value : 'READ'
}

function asFinishReason(value: string): FinishReason {
  return value === 'interrupted' || value === 'approval_required' || value === 'max_steps' || value === 'error'
    ? value
    : 'stop'
}

function toCitation(source: unknown): CitationVO {
  return {
    docId: pickNumber(source, 'docId'),
    chunkId: pickNumber(source, 'chunkId'),
    title: pickString(source, 'title'),
    snippet: pickString(source, 'snippet'),
    score: pickNumber(source, 'score'),
  }
}

export function parseSseData(data: string): unknown {
  const trimmed = data.trim()
  if (!trimmed) return undefined
  try {
    return JSON.parse(trimmed) as unknown
  } catch {
    return undefined
  }
}

/**
 * 分发单帧。返回终止原因表示应停止读取（done / approval / error）。
 * 契约要求 approval 事件后流即结束。
 */
export function dispatchFrame(frame: SseFrame, handlers: StreamHandlers): StreamCloseReason | null {
  const payload = parseSseData(frame.data)
  if (payload === undefined || !isRecord(payload)) {
    handlers.onUnknownEvent?.(frame.event, payload ?? frame.data)
    return null
  }

  switch (frame.event) {
    case 'meta':
      handlers.onMeta?.({
        traceId: pickString(payload, 'traceId'),
        messageId: pickNumber(payload, 'messageId'),
        sessionId: pickNumber(payload, 'sessionId'),
      })
      return null
    case 'agent':
      handlers.onAgent?.({
        agentType: asAgentType(pickString(payload, 'agentType')),
        reason: pickOptionalString(payload, 'reason'),
      })
      return null
    case 'delta':
      handlers.onDelta?.({ text: pickString(payload, 'text') })
      return null
    case 'tool_call':
      handlers.onToolCall?.({
        callId: pickString(payload, 'callId'),
        name: pickString(payload, 'name'),
        args: pickRecord(payload, 'args'),
        risk: asRisk(pickString(payload, 'risk')),
      })
      return null
    case 'tool_result':
      handlers.onToolResult?.({
        callId: pickString(payload, 'callId'),
        name: pickString(payload, 'name'),
        ok: pickBoolean(payload, 'ok', true),
        summary: pickOptionalString(payload, 'summary'),
        latencyMs: pickNumber(payload, 'latencyMs'),
      })
      return null
    case 'citation':
      handlers.onCitation?.(toCitation(payload))
      return null
    case 'approval':
      handlers.onApproval?.({
        approvalId: pickNumber(payload, 'approvalId', pickNumber(payload, 'id')),
        title: pickString(payload, 'title', '待审批操作'),
        detail: pickRecord(payload, 'detail'),
        risk: asRisk(pickString(payload, 'risk')),
        expiresAt: pickString(payload, 'expiresAt'),
      })
      return 'approval_required'
    case 'usage':
      handlers.onUsage?.({
        promptTokens: pickNumber(payload, 'promptTokens'),
        completionTokens: pickNumber(payload, 'completionTokens'),
        costCents: pickNumber(payload, 'costCents'),
        model: pickOptionalString(payload, 'model'),
      })
      return null
    case 'done':
      handlers.onDone?.({
        messageId: pickNumber(payload, 'messageId'),
        finishReason: asFinishReason(pickString(payload, 'finishReason', 'stop')),
      })
      return 'done'
    case 'error':
      handlers.onError?.({
        code: pickNumber(payload, 'code', -1),
        message: pickString(payload, 'message', '模型服务异常'),
      })
      return 'error'
    default:
      handlers.onUnknownEvent?.(frame.event, payload)
      return null
  }
}
