<template>
  <div class="chat-view">
    <SessionList
      :sessions="chat.sessions"
      :active-id="chat.currentSessionId"
      :loading="chat.sessionsLoading"
      :error="chat.sessionsError"
      @create="onCreate"
      @select="onSelect"
      @remove="onRemove"
      @refresh="onRefreshSessions"
    />

    <section class="chat-main">
      <header class="chat-main__head">
        <div class="chat-main__head-left">
          <AgentBadge :agent="chat.currentAgent" :reason="chat.agentReason" />
          <span class="chat-main__title ellipsis">
            {{ chat.currentSession?.title || '新会话' }}
          </span>
        </div>
        <div class="chat-main__head-right">
          <span v-if="chat.traceId" class="chat-main__trace mono" :title="chat.traceId">
            trace {{ shortTrace }}
          </span>
          <span v-if="chat.usage" class="chat-main__usage mono">
            ↑{{ formatTokens(chat.usage.promptTokens) }} ↓{{ formatTokens(chat.usage.completionTokens) }}
            · {{ formatCents(chat.usage.costCents) }}
          </span>
          <el-tag v-if="finishMeta" size="small" :type="finishMeta.tone" effect="plain">
            {{ finishMeta.label }}
          </el-tag>
          <el-button size="small" text :disabled="chat.streaming" @click="chat.reloadCurrentMessages()">
            刷新
          </el-button>
        </div>
      </header>

      <div ref="scrollRef" class="chat-main__messages scroll-area" @scroll="onScroll">
        <DataState
          :loading="chat.messagesLoading && chat.messages.length === 0"
          :error="chat.messagesError"
          :empty="chat.messages.length === 0 && !chat.streaming"
          empty-text="开始新的对话"
          empty-description="从左侧选择会话，或直接在下方输入问题发送"
          @retry="chat.reloadCurrentMessages()"
        >
          <MessageBubble
            v-for="message in chat.messages"
            :key="message.id"
            :message="message"
            :deciding-approval-id="chat.decidingApprovalId"
            @decide="onDecide"
          />
        </DataState>

        <el-alert
          v-if="chat.lastError && !lastMessageHasError"
          class="chat-main__alert"
          type="error"
          :closable="false"
          show-icon
          :title="chat.lastError"
        />
      </div>

      <ChatComposer :streaming="chat.streaming" @send="onSend" @stop="onStop" />
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import type { ApprovalDecisionPayload } from '@/types'
import { useChatStore } from '@/stores/chat'
import { FINISH_REASON_META, formatCents, formatTokens, metaOf } from '@/utils/format'
import AgentBadge from '@/components/chat/AgentBadge.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import MessageBubble from '@/components/chat/MessageBubble.vue'
import SessionList from '@/components/chat/SessionList.vue'
import DataState from '@/components/common/DataState.vue'

const chat = useChatStore()

const scrollRef = ref<HTMLElement | null>(null)
const stickToBottom = ref(true)

const shortTrace = computed(() => (chat.traceId ? chat.traceId.slice(0, 8) : ''))
const finishMeta = computed(() => (chat.finishReason ? metaOf(FINISH_REASON_META, chat.finishReason) : null))
const lastMessageHasError = computed(() => {
  const last = chat.messages[chat.messages.length - 1]
  return Boolean(last?.error)
})

/** 用轻量快照触发滚动，避免 deep watch 整个消息数组 */
const streamSnapshot = computed(() => {
  const last = chat.messages[chat.messages.length - 1]
  return [
    chat.messages.length,
    last?.content.length ?? 0,
    last?.toolCalls.length ?? 0,
    last?.citations.length ?? 0,
    last?.approvals.length ?? 0,
  ].join(':')
})

function onScroll(): void {
  const el = scrollRef.value
  if (!el) return
  stickToBottom.value = el.scrollHeight - el.scrollTop - el.clientHeight < 100
}

function scrollToBottom(): void {
  const el = scrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

watch(streamSnapshot, () => {
  if (stickToBottom.value) void nextTick(scrollToBottom)
})

async function onCreate(): Promise<void> {
  const session = await chat.createSession()
  if (session) ElMessage.success('已创建新会话')
}

function onSelect(sessionId: number): void {
  void chat.selectSession(sessionId)
}

function onRemove(sessionId: number): void {
  void chat.removeSession(sessionId)
}

function onRefreshSessions(): void {
  void chat.loadSessions()
}

function onSend(text: string): void {
  stickToBottom.value = true
  void chat.send(text)
}

function onStop(): void {
  chat.stop()
}

async function onDecide(payload: ApprovalDecisionPayload): Promise<void> {
  const approval = chat.messages
    .flatMap((message) => message.approvals)
    .find((item) => item.approvalId === payload.approvalId)
  if (!approval) return
  const ok = await chat.decideApproval(approval, payload.decision, payload.comment)
  if (ok) {
    ElMessage.success(payload.decision === 'APPROVE' ? '已同意，操作已提交执行' : '已拒绝该操作')
  }
}

onMounted(async () => {
  await chat.loadSessions()
  if (!chat.currentSessionId && chat.sessions.length > 0) {
    await chat.selectSession(chat.sessions[0].id)
  }
  if (stickToBottom.value) void nextTick(scrollToBottom)
})
</script>

<style scoped lang="scss">
.chat-view {
  display: flex;
  gap: 16px;
  height: 100%;
  min-height: 0;
}

.chat-main {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  min-height: 0;

  &__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 14px;
    background: #fff;
    border: 1px solid var(--ecom-border);
    border-radius: var(--ecom-radius, 10px);
    flex-shrink: 0;
  }

  &__head-left {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  &__head-right {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-shrink: 0;
  }

  &__title {
    max-width: 320px;
    font-size: 14px;
    font-weight: 600;
    color: var(--ecom-text-primary);
  }

  &__trace,
  &__usage {
    font-size: 11px;
    color: var(--ecom-text-secondary);
  }

  &__messages {
    flex: 1;
    padding: 14px 16px;
    background: #fff;
    border: 1px solid var(--ecom-border);
    border-radius: var(--ecom-radius, 10px);
    min-height: 0;
  }

  &__alert {
    margin-top: 8px;
  }
}

@media (max-width: 900px) {
  .chat-view {
    flex-direction: column;
  }

  .chat-main__trace,
  .chat-main__usage {
    display: none;
  }
}
</style>
