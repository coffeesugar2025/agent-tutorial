<template>
  <div class="page-header">
    <div class="page-header__text">
      <div class="page-header__title-row">
        <el-button v-if="showBack" link type="primary" @click="emit('back')">← 返回</el-button>
        <h2 class="page-header__title">{{ title }}</h2>
        <slot name="badge" />
      </div>
      <p v-if="description" class="page-header__desc">{{ description }}</p>
    </div>
    <div class="page-header__actions">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title: string
    description?: string
    showBack?: boolean
  }>(),
  { description: '', showBack: false },
)

const emit = defineEmits<{ back: [] }>()
</script>

<style scoped lang="scss">
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;

  &__text {
    min-width: 0;
  }

  &__title-row {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__title {
    margin: 0;
    font-size: 20px;
    font-weight: 600;
    color: var(--ecom-text-primary);
  }

  &__desc {
    margin: 6px 0 0;
    font-size: 13px;
    color: var(--ecom-text-secondary);
  }

  &__actions {
    display: flex;
    flex-shrink: 0;
    gap: 8px;
    align-items: center;
  }
}
</style>
