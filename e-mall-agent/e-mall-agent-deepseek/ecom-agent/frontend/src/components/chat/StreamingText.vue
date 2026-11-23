<template>
  <div class="streaming-text" :class="{ 'is-streaming': streaming }">
    <div v-if="html" class="markdown-body" v-html="html" />
    <p v-else-if="streaming" class="streaming-text__placeholder">正在生成…</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = withDefaults(defineProps<{ text: string; streaming?: boolean }>(), { streaming: false })

const html = computed(() => renderMarkdown(props.text))
</script>

<style scoped lang="scss">
.streaming-text {
  &__placeholder {
    margin: 0;
    font-size: 13px;
    color: var(--ecom-text-placeholder);
  }

  // 光标跟在最后一段内容后面
  &.is-streaming :deep(.markdown-body > :last-child)::after {
    display: inline-block;
    width: 2px;
    height: 1em;
    margin-left: 3px;
    vertical-align: -2px;
    content: '';
    background: var(--ecom-primary);
    animation: caret-blink 0.9s steps(2, start) infinite;
  }
}

@keyframes caret-blink {
  0%,
  100% {
    opacity: 1;
  }

  50% {
    opacity: 0;
  }
}
</style>
