<script setup lang="ts">
import type { ToolTrace as Trace } from '../types'
import { toolLabel } from '../api/sse'

defineProps<{ traces: Trace[] }>()

function argsText(args: Record<string, unknown>): string {
  try {
    return JSON.stringify(args)
  } catch {
    return String(args)
  }
}
</script>

<template>
  <div class="traces" v-if="traces.length">
    <div v-for="t in traces" :key="`${t.index}-${t.name}`" class="trace" :class="t.status">
      <span class="trace-dot" />
      <div class="trace-main">
        <div>
          <span class="trace-name">{{ toolLabel(t.name) }}</span>
          <span class="trace-status">
            {{ t.status === 'running' ? '调用中…' : t.status === 'success' ? '完成' : '失败' }}
          </span>
        </div>
        <div class="trace-args">{{ argsText(t.args) }}</div>
        <div class="trace-summary" v-if="t.summary">{{ t.summary }}</div>
      </div>
    </div>
  </div>
</template>
