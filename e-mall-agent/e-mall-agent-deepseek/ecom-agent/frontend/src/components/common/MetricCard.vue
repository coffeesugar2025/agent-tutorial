<template>
  <div class="metric-card" :class="`metric-card--${tone}`">
    <div class="metric-card__label">
      {{ label }}
      <el-tooltip v-if="hint" :content="hint" placement="top">
        <span class="metric-card__hint">?</span>
      </el-tooltip>
    </div>
    <div class="metric-card__value">
      {{ value }}<span v-if="unit" class="metric-card__unit">{{ unit }}</span>
    </div>
    <div v-if="footer || $slots.footer" class="metric-card__footer">
      <slot name="footer">{{ footer }}</slot>
    </div>
  </div>
</template>

<script setup lang="ts">
type Tone = 'default' | 'primary' | 'success' | 'warning' | 'danger'

withDefaults(
  defineProps<{
    label: string
    value: string | number
    unit?: string
    hint?: string
    footer?: string
    tone?: Tone
  }>(),
  { unit: '', hint: '', footer: '', tone: 'default' },
)
</script>

<style scoped lang="scss">
.metric-card {
  padding: 14px 16px;
  background: var(--ecom-bg-card);
  border: 1px solid var(--ecom-border);
  border-left: 3px solid var(--ecom-primary);
  border-radius: var(--ecom-radius);
  box-shadow: var(--ecom-shadow);

  &--success {
    border-left-color: var(--ecom-success);
  }

  &--warning {
    border-left-color: var(--ecom-warning);
  }

  &--danger {
    border-left-color: var(--ecom-danger);
  }

  &--default {
    border-left-color: var(--ecom-info);
  }

  &__label {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: var(--ecom-text-secondary);
  }

  &__hint {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 13px;
    height: 13px;
    font-size: 10px;
    color: #fff;
    background: #cbd5e1;
    border-radius: 50%;
    cursor: help;
  }

  &__value {
    margin-top: 6px;
    font-size: 24px;
    font-weight: 600;
    line-height: 1.2;
    color: var(--ecom-text-primary);
    font-variant-numeric: tabular-nums;
  }

  &__unit {
    margin-left: 3px;
    font-size: 12px;
    font-weight: 400;
    color: var(--ecom-text-secondary);
  }

  &__footer {
    margin-top: 6px;
    font-size: 12px;
    color: var(--ecom-text-secondary);
  }
}
</style>
