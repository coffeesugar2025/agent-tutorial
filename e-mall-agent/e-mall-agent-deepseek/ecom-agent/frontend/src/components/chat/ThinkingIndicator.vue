<template>
  <div class="thinking">
    <span class="thinking__dots">
      <i /><i /><i />
    </span>
    <span class="thinking__text">{{ text }}</span>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ text?: string }>(), { text: '思考中…' })
</script>

<style scoped lang="scss">
.thinking {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 13px;
  color: var(--ecom-text-secondary);

  &__dots {
    display: inline-flex;
    gap: 3px;

    i {
      width: 5px;
      height: 5px;
      background: var(--ecom-primary);
      border-radius: 50%;
      opacity: 0.35;
      animation: thinking-bounce 1.1s infinite ease-in-out;

      &:nth-child(2) {
        animation-delay: 0.15s;
      }

      &:nth-child(3) {
        animation-delay: 0.3s;
      }
    }
  }
}

@keyframes thinking-bounce {
  0%,
  70%,
  100% {
    transform: translateY(0);
    opacity: 0.35;
  }

  35% {
    transform: translateY(-3px);
    opacity: 1;
  }
}
</style>
