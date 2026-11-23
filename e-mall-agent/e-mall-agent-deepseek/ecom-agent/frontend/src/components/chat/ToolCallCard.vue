<template>
  <div class="tool-card" :class="`is-${toolCall.status}`">
    <button type="button" class="tool-card__head" @click="expanded = !expanded">
      <span class="tool-card__status">{{ statusIcon }}</span>
      <span class="tool-card__name mono">{{ toolCall.name }}</span>
      <el-tag size="small" :type="riskMeta.tone" effect="plain" class="tool-card__risk">
        {{ riskMeta.label }}
      </el-tag>
      <span class="tool-card__spacer" />
      <span v-if="toolCall.summary" class="tool-card__summary ellipsis">{{ toolCall.summary }}</span>
      <span v-if="typeof toolCall.latencyMs === 'number'" class="tool-card__latency mono">
        {{ formatLatency(toolCall.latencyMs) }}
      </span>
      <span class="tool-card__chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>

    <div v-if="expanded" class="tool-card__body">
      <div class="tool-card__section-title">调用参数</div>
      <pre class="tool-card__json">{{ argsText }}</pre>
      <div v-if="toolCall.summary" class="tool-card__section-title">返回摘要</div>
      <p v-if="toolCall.summary" class="tool-card__summary-full">{{ toolCall.summary }}</p>
      <div class="tool-card__footer">
        <span class="mono">callId: {{ toolCall.callId || '—' }}</span>
        <span>状态：{{ statusLabel }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatToolCall } from '@/types'
import { RISK_META, formatJson, formatLatency, metaOf } from '@/utils/format'

const props = defineProps<{ toolCall: ChatToolCall }>()

const expanded = ref(false)

const statusIcon = computed(() => {
  if (props.toolCall.status === 'running') return '◌'
  return props.toolCall.status === 'ok' ? '✓' : '✕'
})

const statusLabel = computed(() => {
  if (props.toolCall.status === 'running') return '执行中'
  return props.toolCall.status === 'ok' ? '成功' : '失败'
})

const riskMeta = computed(() => metaOf(RISK_META, props.toolCall.risk))
const argsText = computed(() => formatJson(props.toolCall.args ?? {}))
</script>

<style scoped lang="scss">
.tool-card {
  margin-top: 8px;
  overflow: hidden;
  background: #fbfcfe;
  border: 1px solid var(--ecom-border);
  border-left: 3px solid #94a3b8;
  border-radius: 8px;

  &.is-ok {
    border-left-color: var(--ecom-success);
  }

  &.is-failed {
    border-left-color: var(--ecom-danger);
  }

  &.is-running {
    border-left-color: var(--ecom-primary);
  }

  &__head {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 8px 10px;
    font-size: 12px;
    text-align: left;
    cursor: pointer;
    background: transparent;
    border: 0;

    &:hover {
      background: #f4f7fd;
    }
  }

  &__status {
    width: 14px;
    font-size: 12px;
    color: var(--ecom-text-secondary);
    text-align: center;
  }

  &.is-ok &__status {
    color: var(--ecom-success);
  }

  &.is-failed &__status {
    color: var(--ecom-danger);
  }

  &.is-running &__status {
    color: var(--ecom-primary);
    animation: spin 1.2s linear infinite;
  }

  &__name {
    font-size: 12px;
    font-weight: 600;
    color: #0f172a;
  }

  &__risk {
    flex-shrink: 0;
  }

  &__spacer {
    flex: 1;
  }

  &__summary {
    max-width: 260px;
    color: var(--ecom-text-secondary);
  }

  &__latency {
    color: var(--ecom-text-secondary);
    flex-shrink: 0;
  }

  &__chevron {
    color: var(--ecom-text-secondary);
    flex-shrink: 0;
  }

  &__body {
    padding: 0 10px 10px;
    border-top: 1px dashed var(--ecom-border);
  }

  &__section-title {
    margin: 8px 0 4px;
    font-size: 11px;
    font-weight: 600;
    color: var(--ecom-text-secondary);
  }

  &__json {
    max-height: 220px;
    margin: 0;
    padding: 8px 10px;
    overflow: auto;
    font-family: var(--ecom-font-mono, monospace);
    font-size: 11.5px;
    line-height: 1.55;
    color: #334155;
    white-space: pre-wrap;
    word-break: break-word;
    background: #fff;
    border: 1px solid var(--ecom-border);
    border-radius: 6px;
  }

  &__summary-full {
    margin: 0;
    font-size: 12px;
    color: var(--ecom-text-regular);
  }

  &__footer {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    margin-top: 8px;
    font-size: 11px;
    color: var(--ecom-text-placeholder);
  }
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
