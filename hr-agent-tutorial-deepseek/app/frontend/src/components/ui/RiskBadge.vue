<script setup>
import { computed } from 'vue'
import AppIcon from '../AppIcon.vue'

const props = defineProps({
  risk: { type: String, default: 'low' },
  label: { type: String, default: '' },
  size: { type: String, default: 'md' },
})

const RISK = {
  high: { label: '高风险', icon: 'shield-alert', className: 'risk--high' },
  medium: { label: '中风险', icon: 'shield', className: 'risk--medium' },
  low: { label: '低风险', icon: 'shield', className: 'risk--low' },
}

const info = computed(() => RISK[String(props.risk).toLowerCase()] || { label: '风险未知', icon: 'shield', className: 'risk--unknown' })
</script>

<template>
  <span class="risk-badge" :class="[info.className, `risk-badge--${size}`]" :title="`敏感操作风险等级：${info.label}`">
    <AppIcon :name="info.icon" :size="size === 'sm' ? 13 : 15" />
    <span>{{ label || info.label }}</span>
  </span>
</template>

<style scoped>
.risk-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.6;
  border: 1px solid transparent;
  white-space: nowrap;
}
.risk-badge--sm {
  padding: 1px 7px;
  font-size: 11.5px;
}
.risk--high {
  color: #b42318;
  background: #fef3f2;
  border-color: #fecdca;
}
.risk--medium {
  color: #b54708;
  background: #fffaeb;
  border-color: #fedf89;
}
.risk--low {
  color: #027a48;
  background: #ecfdf3;
  border-color: #abefc6;
}
.risk--unknown {
  color: var(--text-2);
  background: var(--surface-2);
  border-color: var(--border);
}
</style>
