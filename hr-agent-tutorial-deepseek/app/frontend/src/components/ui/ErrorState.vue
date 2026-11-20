<script setup>
import AppIcon from '../AppIcon.vue'

defineProps({
  title: { type: String, default: '加载失败' },
  message: { type: String, default: '请稍后重试。' },
  retryLabel: { type: String, default: '重新加载' },
  loading: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})

const emit = defineEmits(['retry'])
</script>

<template>
  <div class="error-state" :class="{ 'error-state--compact': compact }" role="alert">
    <div class="error-state__icon">
      <AppIcon name="alert" :size="compact ? 20 : 26" />
    </div>
    <div class="error-state__content">
      <p class="error-state__title">{{ title }}</p>
      <p class="error-state__message">{{ message }}</p>
      <div class="error-state__actions">
        <button type="button" class="btn btn--primary btn--sm" :disabled="loading" @click="emit('retry')">
          <AppIcon name="refresh" :size="15" :class="{ spinning: loading }" />
          <span>{{ loading ? '正在重试…' : retryLabel }}</span>
        </button>
        <slot name="actions" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.error-state {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  padding: 24px;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius);
  background: linear-gradient(180deg, #fff, var(--danger-soft));
  box-shadow: var(--shadow-sm);
}
.error-state--compact {
  padding: 16px;
  gap: 12px;
  border-radius: var(--radius-sm);
}
.error-state__icon {
  display: grid;
  place-items: center;
  flex: none;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  color: var(--danger);
  background: #fff;
  border: 1px solid var(--danger-border);
}
.error-state--compact .error-state__icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
}
.error-state__content { min-width: 0; }
.error-state__title {
  margin: 0;
  font-weight: 650;
  color: var(--text);
}
.error-state__message {
  margin: 4px 0 0;
  color: var(--text-2);
  font-size: 14px;
  line-height: 1.75;
  overflow-wrap: anywhere;
}
.error-state__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 14px;
}
</style>
