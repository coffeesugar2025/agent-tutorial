<template>
  <div class="data-state">
    <div v-if="loading" class="data-state__loading">
      <el-skeleton :rows="rows" animated />
    </div>
    <div v-else-if="error" class="data-state__error">
      <el-alert type="error" :closable="false" show-icon :title="error" />
      <el-button class="data-state__retry" size="small" @click="emit('retry')">重试</el-button>
    </div>
    <EmptyState v-else-if="empty" :title="emptyText" :description="emptyDescription">
      <slot name="empty" />
    </EmptyState>
    <slot v-else />
  </div>
</template>

<script setup lang="ts">
import EmptyState from './EmptyState.vue'

withDefaults(
  defineProps<{
    loading?: boolean
    error?: string
    empty?: boolean
    emptyText?: string
    emptyDescription?: string
    rows?: number
  }>(),
  {
    loading: false,
    error: '',
    empty: false,
    emptyText: '暂无数据',
    emptyDescription: '',
    rows: 4,
  },
)

const emit = defineEmits<{ retry: [] }>()
</script>

<style scoped lang="scss">
.data-state {
  &__loading {
    padding: 8px 4px;
  }

  &__error {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__retry {
    flex-shrink: 0;
  }
}
</style>
