<template>
  <span class="agent-badge" :class="[`agent-badge--${meta.tone}`, { 'agent-badge--compact': compact }]">
    <span class="agent-badge__dot" />
    <span class="agent-badge__label">{{ meta.label }}</span>
    <span v-if="reason" class="agent-badge__reason">{{ reason }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { AGENT_META, metaOf } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    agent?: string
    reason?: string
    compact?: boolean
  }>(),
  { agent: 'SUPERVISOR', reason: '', compact: false },
)

const meta = computed(() => metaOf(AGENT_META, props.agent))
</script>

<style scoped lang="scss">
.agent-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  padding: 2px 8px;
  font-size: 12px;
  line-height: 18px;
  color: #334155;
  background: #f1f5f9;
  border: 1px solid #e2e8f0;
  border-radius: 999px;

  &__dot {
    width: 6px;
    height: 6px;
    background: currentColor;
    border-radius: 50%;
    flex-shrink: 0;
  }

  &__label {
    font-weight: 600;
    white-space: nowrap;
  }

  &__reason {
    overflow: hidden;
    color: #64748b;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &--success {
    color: #166534;
    background: #f0fdf4;
    border-color: #bbf7d0;
  }

  &--warning {
    color: #92400e;
    background: #fffbeb;
    border-color: #fde68a;
  }

  &--danger {
    color: #991b1b;
    background: #fef2f2;
    border-color: #fecaca;
  }

  &--info {
    color: #1e40af;
    background: #eff6ff;
    border-color: #bfdbfe;
  }

  &--compact {
    padding: 0 6px;
    font-size: 11px;
    line-height: 16px;
  }
}
</style>
