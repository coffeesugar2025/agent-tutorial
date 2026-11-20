<script setup>
import AppIcon from '../AppIcon.vue'

defineProps({
  icon: { type: String, default: 'sparkles' },
  title: { type: String, default: '暂无数据' },
  message: { type: String, default: '' },
})
</script>

<template>
  <div class="empty-state">
    <div class="empty-state__icon"><AppIcon :name="icon" :size="22" /></div>
    <p class="empty-state__title">{{ title }}</p>
    <p v-if="message" class="empty-state__message">{{ message }}</p>
    <div v-if="$slots.default" class="empty-state__action"><slot /></div>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 34px 20px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: linear-gradient(180deg, #fff, var(--surface-2));
}
.empty-state__icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 13px;
  color: var(--brand);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
}
.empty-state__title {
  margin: 12px 0 0;
  font-weight: 600;
  color: var(--text);
  font-size: 15px;
}
.empty-state__message {
  margin: 6px 0 0;
  max-width: 34em;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.7;
}
.empty-state__action { margin-top: 14px; }
</style>
