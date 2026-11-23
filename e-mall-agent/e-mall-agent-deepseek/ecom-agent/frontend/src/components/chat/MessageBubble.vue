<template>
  <div class="message" :class="[`message--${message.role}`]">
    <div v-if="isAssistant" class="message__avatar">AI</div>

    <div class="message__body">
      <div v-if="isAssistant || message.interrupted" class="message__meta">
        <AgentBadge v-if="isAssistant" :agent="message.agentType" compact />
        <span v-if="message.interrupted" class="message__flag">已中断</span>
        <span v-if="message.createdAt" class="message__time">{{ formatTimeShort(message.createdAt) }}</span>
      </div>

      <div class="message__bubble">
        <template v-if="message.role === 'user'">
          <p class="message__user-text">{{ message.content }}</p>
        </template>
        <template v-else-if="message.role === 'assistant'">
          <StreamingText :text="message.content" :streaming="message.streaming" />
          <ThinkingIndicator v-if="message.streaming && !message.content" text="思考中…" />
        </template>
        <p v-else class="message__system-text">{{ message.content }}</p>

        <el-alert
          v-if="message.error"
          class="message__error"
          type="error"
          :closable="false"
          show-icon
          :title="message.error"
        />

        <div v-if="message.toolCalls.length" class="message__tools">
          <ToolCallCard
            v-for="call in message.toolCalls"
            :key="call.callId || call.name"
            :tool-call="call"
          />
        </div>

        <ApprovalCard
          v-for="approval in message.approvals"
          :key="approval.approvalId"
          :approval="approval"
          :busy="decidingApprovalId === approval.approvalId"
          @decide="onDecision"
        />

        <CitationList :citations="message.citations" />

        <div v-if="statsText" class="message__stats mono">{{ statsText }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ApprovalDecisionPayload, ChatMessage } from '@/types'
import { formatCents, formatTimeShort, formatTokens } from '@/utils/format'
import AgentBadge from './AgentBadge.vue'
import ApprovalCard from './ApprovalCard.vue'
import CitationList from './CitationList.vue'
import StreamingText from './StreamingText.vue'
import ThinkingIndicator from './ThinkingIndicator.vue'
import ToolCallCard from './ToolCallCard.vue'

const props = withDefaults(
  defineProps<{
    message: ChatMessage
    decidingApprovalId?: number | null
  }>(),
  { decidingApprovalId: null },
)

const emit = defineEmits<{ decide: [payload: ApprovalDecisionPayload] }>()

const isAssistant = computed(() => props.message.role === 'assistant')

const statsText = computed(() => {
  const parts: string[] = []
  if (typeof props.message.tokenIn === 'number' || typeof props.message.tokenOut === 'number') {
    parts.push(`↑${formatTokens(props.message.tokenIn)} ↓${formatTokens(props.message.tokenOut)}`)
  }
  if (typeof props.message.costCents === 'number') parts.push(formatCents(props.message.costCents))
  return parts.join(' · ')
})

function onDecision(payload: ApprovalDecisionPayload): void {
  emit('decide', payload)
}
</script>

<style scoped lang="scss">
.message {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;

  &--user {
    flex-direction: row-reverse;
  }

  &__avatar {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    font-size: 11px;
    font-weight: 700;
    color: #fff;
    background: linear-gradient(135deg, #2f6bff, #6b93ff);
    border-radius: 8px;
    flex-shrink: 0;
  }

  &__body {
    max-width: min(760px, 82%);
    min-width: 0;
  }

  &--user &__body {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
  }

  &__meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
  }

  &__time {
    font-size: 11px;
    color: var(--ecom-text-placeholder);
  }

  &__flag {
    padding: 0 6px;
    font-size: 11px;
    color: var(--ecom-warning);
    background: #fffbeb;
    border: 1px solid #fde68a;
    border-radius: 999px;
  }

  &__bubble {
    width: 100%;
    padding: 10px 14px;
    background: #fff;
    border: 1px solid var(--ecom-border-light, #eef1f6);
    border-radius: 10px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }

  &--user &__bubble {
    color: #fff;
    background: var(--ecom-primary);
    border-color: var(--ecom-primary);
  }

  &__user-text {
    margin: 0;
    font-size: 14px;
    line-height: 1.7;
    white-space: pre-wrap;
    word-break: break-word;
  }

  &__system-text {
    margin: 0;
    font-size: 12px;
    color: var(--ecom-text-secondary);
  }

  &__error {
    margin-top: 8px;
  }

  &__tools {
    margin-top: 4px;
  }

  &__stats {
    margin-top: 8px;
    font-size: 10.5px;
    color: var(--ecom-text-placeholder);
  }
}
</style>
