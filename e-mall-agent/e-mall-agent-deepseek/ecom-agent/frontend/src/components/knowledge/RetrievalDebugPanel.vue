<template>
  <div class="retrieval">
    <div class="toolbar">
      <el-input
        v-model="query"
        placeholder="输入问题，例如：退货运费谁承担"
        style="width: 340px"
        clearable
        @keyup.enter="search"
      />
      <el-select v-model="mode" style="width: 118px">
        <el-option v-for="value in SEARCH_MODES" :key="value" :label="modeLabel(value)" :value="value" />
      </el-select>
      <el-select v-model="docTypes" multiple collapse-tags placeholder="全部文档类型" style="width: 190px">
        <el-option
          v-for="value in DOC_TYPES"
          :key="value"
          :label="metaOf(DOC_TYPE_META, value).label"
          :value="value"
        />
      </el-select>
      <el-input-number v-model="topK" :min="1" :max="20" size="small" />
      <el-button type="primary" size="small" :loading="loading" @click="search">检索</el-button>
    </div>

    <div v-if="debug" class="retrieval__debug mono">
      latency {{ debug.latencyMs }}ms · denseTopK {{ debug.denseTopK }} · sparseTopK {{ debug.sparseTopK }} · rerankTopN {{ debug.rerankTopN }}
    </div>

    <DataState
      :loading="loading"
      :error="error"
      :empty="!loading && !error && items.length === 0"
      empty-text="输入 query 开始检索调试"
      empty-description="将同时展示 dense / sparse / rerank 三路分数"
      @retry="search"
    >
      <ul class="retrieval__list">
        <li v-for="item in items" :key="`${item.documentId}-${item.chunkId}`" class="hit">
          <div class="hit__head">
            <span class="hit__title ellipsis">{{ item.title }}</span>
            <span class="hit__route mono">{{ item.route }}</span>
            <span class="hit__score">{{ formatScore(item.score) }}</span>
          </div>
          <p class="hit__content">{{ item.content }}</p>
          <div class="hit__scores">
            <div v-for="score in scoresOf(item)" :key="score.label" class="score-bar">
              <span class="score-bar__label">{{ score.label }}</span>
              <div class="score-bar__track">
                <div class="score-bar__fill" :style="{ width: percentOf(score.value) }" />
              </div>
              <span class="score-bar__value mono">{{ formatScore(score.value) }}</span>
            </div>
          </div>
          <div class="hit__meta mono">doc {{ item.documentId }} · chunk {{ item.chunkId }}</div>
        </li>
      </ul>
    </DataState>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { searchKnowledge } from '@/api/knowledge'
import {
  DOC_TYPES,
  SEARCH_MODES,
  type DocType,
  type KnowledgeSearchDebug,
  type KnowledgeSearchItem,
  type SearchMode,
} from '@/types'
import { errorMessage } from '@/utils/guard'
import { formatScore, metaOf, DOC_TYPE_META } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'

interface ScoreBar {
  label: string
  value: number
}

const MODE_LABELS: Record<string, string> = {
  hybrid: '混合检索',
  dense: '向量检索',
  sparse: '关键词检索',
}

const query = ref('')
const mode = ref<SearchMode>('hybrid')
const docTypes = ref<DocType[]>([])
const topK = ref(5)
const loading = ref(false)
const error = ref('')
const items = ref<KnowledgeSearchItem[]>([])
const debug = ref<KnowledgeSearchDebug | null>(null)

function modeLabel(value: string): string {
  return MODE_LABELS[value] ?? value
}

function scoresOf(item: KnowledgeSearchItem): ScoreBar[] {
  const scores: ScoreBar[] = [{ label: '总分', value: item.score }]
  if (typeof item.denseScore === 'number') scores.push({ label: '向量', value: item.denseScore })
  if (typeof item.sparseScore === 'number') scores.push({ label: '关键词', value: item.sparseScore })
  if (typeof item.rerankScore === 'number') scores.push({ label: '重排', value: item.rerankScore })
  return scores
}

function percentOf(value: number): string {
  const clamped = Math.min(1, Math.max(0, value))
  return `${(clamped * 100).toFixed(1)}%`
}

async function search(): Promise<void> {
  const text = query.value.trim()
  if (!text || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const result = await searchKnowledge({
      query: text,
      topK: topK.value,
      docTypes: docTypes.value.length ? docTypes.value : undefined,
      mode: mode.value,
    })
    items.value = result.items ?? []
    debug.value = result.debug ?? null
  } catch (err) {
    error.value = errorMessage(err, '检索失败')
    items.value = []
    debug.value = null
  } finally {
    loading.value = false
  }
}
</script>

<style scoped lang="scss">
.retrieval {
  &__debug {
    margin: 10px 0 4px;
    font-size: 11px;
    color: var(--ecom-text-secondary);
  }

  &__list {
    margin: 10px 0 0;
    padding: 0;
    list-style: none;
  }
}

.hit {
  padding: 10px 12px;
  border: 1px solid var(--ecom-border);
  border-radius: 8px;

  & + & {
    margin-top: 10px;
  }

  &__head {
    display: flex;
    align-items: baseline;
    gap: 10px;
  }

  &__title {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 600;
  }

  &__route {
    font-size: 10px;
    color: var(--ecom-text-secondary);
  }

  &__score {
    font-size: 13px;
    font-weight: 600;
    color: var(--ecom-success);
  }

  &__content {
    margin: 6px 0;
    font-size: 12px;
    line-height: 1.65;
    color: var(--ecom-text-regular);
    white-space: pre-wrap;
  }

  &__scores {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 6px 14px;
    margin-top: 6px;
  }

  &__meta {
    margin-top: 6px;
    font-size: 10px;
    color: var(--ecom-text-placeholder);
  }
}

.score-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;

  &__label {
    width: 42px;
    color: var(--ecom-text-secondary);
    flex-shrink: 0;
  }

  &__track {
    flex: 1;
    height: 5px;
    overflow: hidden;
    background: #eef2f7;
    border-radius: 3px;
  }

  &__fill {
    height: 100%;
    background: linear-gradient(90deg, #6b93ff, #2f6bff);
    border-radius: 3px;
  }

  &__value {
    width: 40px;
    color: var(--ecom-text-secondary);
    text-align: right;
    flex-shrink: 0;
  }
}
</style>
