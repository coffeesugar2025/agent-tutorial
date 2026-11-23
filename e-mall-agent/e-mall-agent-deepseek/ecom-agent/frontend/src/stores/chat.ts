import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as chatApi from '@/api/chat'
import type { AgentType, ApprovalDecision, ChatApproval, ChatMessage, FinishReason, SessionVO, UsageEventData } from '@/types'
import { errorMessage, uid } from '@/utils/guard'
import { createAssistantDraft, createUserMessage, mapMessageVO } from '@/utils/chat'
import { createChatStreamHandlers } from '@/utils/chatStream'
import { streamChat } from '@/utils/sse'

export const useChatStore = defineStore('chat', () => {
  const sessions = ref<SessionVO[]>([])
  const sessionsLoading = ref(false)
  const sessionsError = ref('')
  const currentSessionId = ref<number | null>(null)
  const messages = ref<ChatMessage[]>([])
  const messagesLoading = ref(false)
  const messagesError = ref('')
  const streaming = ref(false)
  const currentAgent = ref<AgentType>('SUPERVISOR')
  const agentReason = ref('')
  const traceId = ref('')
  const usage = ref<UsageEventData | null>(null)
  const finishReason = ref<FinishReason | null>(null)
  const lastError = ref('')
  const pendingApproval = ref<ChatApproval | null>(null)
  const decidingApprovalId = ref<number | null>(null)

  let controller: AbortController | null = null

  const currentSession = computed(
    () => sessions.value.find((session) => session.id === currentSessionId.value) ?? null,
  )
  const hasPendingApproval = computed(() => pendingApproval.value !== null)
  const canSend = computed(() => !streaming.value)

  function resetStreamState(): void {
    traceId.value = ''
    agentReason.value = ''
    usage.value = null
    finishReason.value = null
    lastError.value = ''
    pendingApproval.value = null
  }

  async function loadSessions(): Promise<void> {
    sessionsLoading.value = true
    sessionsError.value = ''
    try {
      sessions.value = await chatApi.listSessions()
    } catch (err) {
      sessionsError.value = errorMessage(err, '会话列表加载失败')
    } finally {
      sessionsLoading.value = false
    }
  }

  async function refreshSessionsSilently(): Promise<void> {
    try {
      sessions.value = await chatApi.listSessions()
    } catch {
      /* 后台刷新失败不打扰用户 */
    }
  }

  async function loadMessages(sessionId: number): Promise<void> {
    messagesLoading.value = true
    messagesError.value = ''
    try {
      const list = await chatApi.listMessages(sessionId)
      if (currentSessionId.value === sessionId) messages.value = list.map(mapMessageVO)
    } catch (err) {
      messagesError.value = errorMessage(err, '消息加载失败')
    } finally {
      messagesLoading.value = false
    }
  }

  async function createSession(title?: string): Promise<SessionVO | null> {
    try {
      const session = await chatApi.createSession(title)
      sessions.value = [session, ...sessions.value.filter((item) => item.id !== session.id)]
      currentSessionId.value = session.id
      messages.value = []
      resetStreamState()
      currentAgent.value = session.agentType ?? 'SUPERVISOR'
      return session
    } catch (err) {
      messagesError.value = errorMessage(err, '新建会话失败')
      return null
    }
  }

  async function selectSession(sessionId: number): Promise<void> {
    if (currentSessionId.value === sessionId && messages.value.length > 0) return
    if (streaming.value) stop()
    currentSessionId.value = sessionId
    messages.value = []
    resetStreamState()
    const session = sessions.value.find((item) => item.id === sessionId)
    if (session?.agentType) currentAgent.value = session.agentType
    await loadMessages(sessionId)
  }

  async function removeSession(sessionId: number): Promise<void> {
    try {
      await chatApi.deleteSession(sessionId)
      sessions.value = sessions.value.filter((item) => item.id !== sessionId)
      if (currentSessionId.value === sessionId) {
        currentSessionId.value = null
        messages.value = []
        resetStreamState()
      }
      if (currentSessionId.value === null && sessions.value.length > 0) {
        await selectSession(sessions.value[0].id)
      }
    } catch {
      /* 错误已由 http 层 toast */
    }
  }

  async function send(content: string): Promise<void> {
    const text = content.trim()
    if (!text || streaming.value) return
    if (currentSessionId.value === null) {
      const created = await createSession()
      if (!created) return
    }
    const sessionId = currentSessionId.value
    if (sessionId === null) return

    resetStreamState()
    messages.value.push(createUserMessage(text))
    messages.value.push(createAssistantDraft(currentAgent.value))
    // push 之后取回响应式代理，流式期间字段修改才会触发渲染
    const draft = messages.value[messages.value.length - 1]
    draft.streaming = true
    streaming.value = true

    const abortController = new AbortController()
    controller = abortController
    const handlers = createChatStreamHandlers({
      draft,
      sessionId,
      onTrace: (trace, messageId) => {
        traceId.value = trace
        if (messageId) draft.id = `srv-${messageId}`
      },
      onAgent: (agent, reason) => {
        currentAgent.value = agent
        agentReason.value = reason ?? ''
      },
      onUsage: (data) => {
        usage.value = data
      },
      onApproval: (approval) => {
        pendingApproval.value = approval
        finishReason.value = 'approval_required'
      },
      onFinish: (reason) => {
        finishReason.value = reason
      },
      onError: (message) => {
        lastError.value = message
      },
    })

    try {
      await streamChat({ sessionId, message: text, clientMsgId: uid('msg') }, handlers, abortController.signal)
    } catch (err) {
      const message = errorMessage(err, '对话失败')
      lastError.value = message
      draft.error = message
    } finally {
      draft.streaming = false
      if (!draft.content && !draft.error && draft.toolCalls.length === 0 && draft.approvals.length === 0) {
        draft.content = '（未收到回复，请检查后端日志或重试）'
      }
      if (controller === abortController) controller = null
      streaming.value = false
      void refreshSessionsSilently()
    }
  }

  /** 停止生成：先中断 fetch，再通知后端做清理（best-effort） */
  function stop(): void {
    if (!streaming.value) return
    controller?.abort()
    controller = null
    streaming.value = false
    finishReason.value = 'interrupted'
    const last = messages.value[messages.value.length - 1]
    if (last?.streaming) {
      last.streaming = false
      last.interrupted = true
    }
    const sessionId = currentSessionId.value
    if (sessionId !== null) void chatApi.interruptSession(sessionId).catch(() => undefined)
  }

  async function decideApproval(
    approval: ChatApproval,
    decision: ApprovalDecision,
    comment = '',
  ): Promise<boolean> {
    if (decidingApprovalId.value !== null) return false
    decidingApprovalId.value = approval.approvalId
    try {
      const result = await chatApi.decideApproval(approval.approvalId, { decision, comment })
      approval.status = result.status
      approval.result = result.result
      if (pendingApproval.value?.approvalId === approval.approvalId) pendingApproval.value = null
      finishReason.value = 'stop'
      void refreshSessionsSilently()
      return true
    } catch (err) {
      lastError.value = errorMessage(err, '审批提交失败')
      return false
    } finally {
      decidingApprovalId.value = null
    }
  }

  async function reloadCurrentMessages(): Promise<void> {
    const sessionId = currentSessionId.value
    if (sessionId !== null && !streaming.value) await loadMessages(sessionId)
  }

  function clearAll(): void {
    if (streaming.value) controller?.abort()
    controller = null
    streaming.value = false
    sessions.value = []
    messages.value = []
    currentSessionId.value = null
    resetStreamState()
  }

  return {
    sessions,
    sessionsLoading,
    sessionsError,
    currentSessionId,
    messages,
    messagesLoading,
    messagesError,
    streaming,
    currentAgent,
    agentReason,
    traceId,
    usage,
    finishReason,
    lastError,
    pendingApproval,
    decidingApprovalId,
    currentSession,
    hasPendingApproval,
    canSend,
    loadSessions,
    loadMessages,
    selectSession,
    createSession,
    removeSession,
    send,
    stop,
    decideApproval,
    reloadCurrentMessages,
    clearAll,
    resetStreamState,
  }
})
