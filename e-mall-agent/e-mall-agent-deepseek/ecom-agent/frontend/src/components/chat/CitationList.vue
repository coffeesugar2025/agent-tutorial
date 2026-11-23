<template>
  <div v-if="citations.length" class="citation-list">
    <div class="citation-list__title">
      引用来源
      <span class="citation-list__count">{{ citations.length }}</span>
    </div>
    <div v-for="(citation, index) in citations" :key="`${citation.docId}-${citation.chunkId}`" class="citation-item">
      <button type="button" class="citation-item__head" @click="toggle(index)">
        <span class="citation-item__index">{{ index + 1 }}</span>
        <span class="citation-item__title ellipsis">{{ citation.title || `文档 ${citation.docId}` }}</span>
        <span class="citation-item__score">{{ formatPercent(citation.score) }}</span>
        <span class="citation-item__chevron">{{ isOpen(index) ? '▾' : '▸' }}</span>
      </button>
      <div v-if="isOpen(index)" class="citation-item__body">
        <p class="citation-item__snippet">{{ citation.snippet || '（该片段为空）' }}</p>
        <div class="citation-item__meta mono">
          docId {{ citation.docId }} · chunkId {{ citation.chunkId }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { CitationVO } from '@/types'
import { formatPercent } from '@/utils/format'

defineProps<{ citations: CitationVO[] }>()

// 用 Set 的副本触发响应式更新
const openSet = ref<Set<number>>(new Set())

function isOpen(index: number): boolean {
  return openSet.value.has(index)
}

function toggle(index: number): void {
  const next = new Set(openSet.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  openSet.value = next
}
</script>

<style scoped lang="scss">
.citation-list {
  margin-top: 10px;
  padding: 8px 10px;
  background: #f8fafc;
  border: 1px solid var(--ecom-border);
  border-radius: 8px;

  &__title {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 4px;
    font-size: 12px;
    font-weight: 600;
    color: var(--ecom-text-regular);
  }

  &__count {
    padding: 0 6px;
    font-size: 11px;
    font-weight: 500;
    color: var(--ecom-primary);
    background: #e8efff;
    border-radius: 8px;
  }
}

.citation-item {
  & + & {
    border-top: 1px dashed var(--ecom-border);
  }

  &__head {
    display: flex;
    align-items: center;
    gap: 8px;
    width: 100%;
    padding: 5px 0;
    font-size: 12px;
    text-align: left;
    cursor: pointer;
    background: transparent;
    border: 0;

    &:hover .citation-item__title {
      color: var(--ecom-primary);
    }
  }

  &__index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    font-size: 10px;
    color: var(--ecom-text-secondary);
    background: #e2e8f0;
    border-radius: 50%;
    flex-shrink: 0;
  }

  &__title {
    flex: 1;
    overflow: hidden;
    color: var(--ecom-text-primary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__score {
    font-size: 11px;
    color: var(--ecom-success);
    flex-shrink: 0;
  }

  &__chevron {
    color: var(--ecom-text-placeholder);
    flex-shrink: 0;
  }

  &__body {
    padding: 2px 0 8px 24px;
  }

  &__snippet {
    margin: 0;
    font-size: 12px;
    line-height: 1.65;
    color: var(--ecom-text-regular);
    white-space: pre-wrap;
  }

  &__meta {
    margin-top: 4px;
    font-size: 10px;
    color: var(--ecom-text-placeholder);
  }
}
</style>
