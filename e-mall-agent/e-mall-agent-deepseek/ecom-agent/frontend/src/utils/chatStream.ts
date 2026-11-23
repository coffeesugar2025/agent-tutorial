/** 把 SSE 事件流映射到一条助手消息草稿（store 之外的纯逻辑，便于复用与测试） */
import type { AgentType, ChatApproval, ChatMessage, FinishReason, UsageEventData } from '@/types'
import type { StreamHandlers } from '@/utils/sseParser'
import { appendCitation, applyToolResult, approvalFromEvent } from './chat'

export interface ChatStreamCallbacks {
  draft: ChatMessage
  sessionId: number
  onTrace?: (traceId: string, messageId: number) => void
  onAgent?: (agentType: AgentType, reason?: string) => void
  onUsage?: (usage: UsageEventData) => void
  onApproval?: (approval: ChatApproval) => void
  onFinish?: (reason: FinishReason) => void
  onError?: (message: string) => void
  onUnknown?: (event: string) => void
}

export function createChatStreamHandlers(callbacks: ChatStreamCallbacks): StreamHandlers {
  const { draft } = callbacks

  return {
    onMeta: (data) => {
      callbacks.onTrace?.(data.traceId, data.messageId)
      draft.traceId = data.traceId
      if (data.messageId) draft.id = `srv-${data.messageId}`
    },
    onAgent: (data) => {
      callbacks.onAgent?.(data.agentType, data.reason)
      draft.agentType = data.agentType
    },
    onDelta: (data) => {
      draft.content += data.text
    },
    onToolCall: (data) => {
      draft.toolCalls.push({
        callId: data.callId,
        name: data.name,
        args: data.args,
        risk: data.risk,
        status: 'running',
      })
    },
    onToolResult: (data) => {
      applyToolResult(draft.toolCalls, data)
    },
    onCitation: (data) => {
      appendCitation(draft.citations, data)
    },
    onApproval: (data) => {
      const approval = approvalFromEvent(data, callbacks.sessionId)
      draft.approvals.push(approval)
      callbacks.onApproval?.(approval)
    },
    onUsage: (data) => {
      callbacks.onUsage?.(data)
      draft.tokenIn = data.promptTokens
      draft.tokenOut = data.completionTokens
      draft.costCents = data.costCents
    },
    onDone: (data) => {
      callbacks.onFinish?.(data.finishReason)
      if (data.messageId) draft.id = `srv-${data.messageId}`
    },
    onError: (data) => {
      callbacks.onError?.(data.message)
      draft.error = data.message
    },
    onClose: (reason) => {
      if (reason === 'aborted') callbacks.onFinish?.('interrupted')
    },
    onUnknownEvent: (event) => {
      callbacks.onUnknown?.(event)
    },
  }
}
