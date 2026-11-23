<template>
  <div class="empty-state">
    <el-empty :description="title" :image-size="imageSize">
      <p v-if="description" class="empty-state__desc">{{ description }}</p>
      <slot />
    </el-empty>
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    title?: string
    description?: string
    imageSize?: number
  }>(),
  { title: '暂无数据', description: '', imageSize: 96 },
)
</script>

<style scoped lang="scss">
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 12px;

  &__desc {
    margin: 0 0 12px;
    font-size: 13px;
    color: var(--ecom-text-secondary);
  }

  :deep(.el-empty__description p) {
    color: var(--ecom-text-regular);
  }
}
</style>
