<script setup>
import { computed } from 'vue'
import AppIcon from '../AppIcon.vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [String, Number], default: '—' },
  unit: { type: String, default: '' },
  hint: { type: String, default: '' },
  icon: { type: String, default: 'chart' },
  tone: { type: String, default: 'brand' },
  delta: { type: Object, default: null },
})

const deltaView = computed(() => {
  if (!props.delta) return null
  const { text, good, direction } = props.delta
  return {
    text,
    className: direction === 'flat' ? 'delta--flat' : good ? 'delta--good' : 'delta--bad',
    icon: direction === 'up' ? 'arrow-up-right' : direction === 'down' ? 'arrow-down-left' : 'minus',
  }
})
</script>

<template>
  <article class="metric" :class="`metric--${tone}`">
    <header class="metric__head">
      <span class="metric__label">{{ label }}</span>
      <span class="metric__icon"><AppIcon :name="icon" :size="16" /></span>
    </header>
    <div class="metric__value-row">
      <span class="metric__value">{{ value }}<small v-if="unit">{{ unit }}</small></span>
      <span v-if="deltaView" class="delta" :class="deltaView.className">
        <AppIcon :name="deltaView.icon" :size="12" />
        {{ deltaView.text }}
      </span>
    </div>
    <p v-if="hint" class="metric__hint">{{ hint }}</p>
  </article>
</template>

<style scoped>
.metric {
  position: relative;
  padding: 16px 16px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.metric::before {
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 3px;
  background: linear-gradient(90deg, #6366f1, #a5b4fc);
}
.metric--success::before { background: linear-gradient(90deg, #10b981, #6ee7b7); }
.metric--warning::before { background: linear-gradient(90deg, #f59e0b, #fcd34d); }
.metric--violet::before { background: linear-gradient(90deg, #8b5cf6, #c4b5fd); }
.metric--slate::before { background: linear-gradient(90deg, #64748b, #cbd5e1); }
.metric__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.metric__label { font-size: 12px; color: var(--text-3); font-weight: 550; }
.metric__icon {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--brand-50);
  color: var(--brand-700);
  flex: none;
}
.metric--success .metric__icon { background: var(--success-soft); color: var(--success); }
.metric--warning .metric__icon { background: var(--warning-soft); color: var(--warning); }
.metric--violet .metric__icon { background: #f4f3ff; color: #5925dc; }
.metric--slate .metric__icon { background: var(--surface-3); color: var(--text-2); }
.metric__value-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-top: 9px;
}
.metric__value {
  font-size: 28px;
  font-weight: 750;
  letter-spacing: -0.035em;
  line-height: 1.15;
  color: var(--text);
}
.metric__value small { margin-left: 3px; font-size: 12px; font-weight: 600; color: var(--text-3); }
.metric__hint {
  margin: 7px 0 0;
  color: var(--text-4);
  font-size: 10.5px;
  line-height: 1.6;
}
.delta {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10.5px;
  font-weight: 650;
  white-space: nowrap;
}
.delta--good { color: var(--success); background: var(--success-soft); }
.delta--bad { color: var(--danger); background: var(--danger-soft); }
.delta--flat { color: var(--text-3); background: var(--surface-3); }
</style>
