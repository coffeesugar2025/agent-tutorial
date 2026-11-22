<script setup lang="ts">
import { computed } from 'vue'
import type { ChatMessage } from '../types'
import { INTENT_LABELS } from '../types'
import ToolTrace from './ToolTrace.vue'
import CardList from './CardList.vue'

const props = defineProps<{ message: ChatMessage }>()
const intentLabel = computed(() =>
  props.message.intent ? (INTENT_LABELS[props.message.intent] ?? props.message.intent) : '',
)
</script>

<template>
  <div class="msg" :class="message.role">
    <div class="avatar" :class="message.role === 'assistant' ? 'bot' : 'human'">
      {{ message.role === 'assistant' ? '栈' : '我' }}
    </div>
    <div class="msg-body">
      <div class="bubble">
        <div class="intent-chip" v-if="intentLabel && message.role === 'assistant'">
          <i /> 意图识别：{{ intentLabel }}
        </div>
        {{ message.content }}<span class="cursor" v-if="message.streaming" />
      </div>

      <ToolTrace :traces="message.traces" />
      <CardList :cards="message.cards" />

      <div class="msg-error" v-if="message.error">⚠ {{ message.error }}</div>
      <div class="msg-meta" v-if="message.meta && message.role === 'assistant'">
        用时 {{ message.meta.elapsed_ms }}ms · 调用 {{ message.meta.tool_calls }} 次工具 · 数据来自 MCP 实时查询
      </div>
    </div>
  </div>
</template>
