<template>
  <DataState
    :loading="loading"
    :error="error"
    :empty="!loading && !error && models.length === 0"
    empty-text="暂无模型信息"
    @retry="emit('retry')"
  >
    <div class="model-grid">
      <div
        v-for="model in models"
        :key="`${model.provider}-${model.model}`"
        class="model-card"
        :class="{ 'is-down': !model.healthy }"
      >
        <div class="model-card__head">
          <span class="model-card__dot" :class="model.healthy ? 'is-ok' : 'is-down'" />
          <span class="model-card__name mono">{{ model.model }}</span>
          <el-tag size="small" :type="metaOf(CIRCUIT_META, model.circuit).tone" effect="plain">
            {{ metaOf(CIRCUIT_META, model.circuit).label }}
          </el-tag>
        </div>
        <div class="model-card__meta">{{ model.provider }} · {{ model.role }}</div>
        <div class="model-card__stats">
          <div class="model-card__stat">
            <span>平均延迟</span>
            <strong>{{ formatLatency(model.avgLatencyMs) }}</strong>
          </div>
          <div class="model-card__stat">
            <span>调用次数</span>
            <strong>{{ formatNumber(model.calls) }}</strong>
          </div>
          <div class="model-card__stat">
            <span>健康状态</span>
            <strong :class="model.healthy ? 'text-success' : 'text-danger'">
              {{ model.healthy ? '正常' : '异常' }}
            </strong>
          </div>
        </div>
      </div>
    </div>
  </DataState>
</template>

<script setup lang="ts">
import type { ModelHealthVO } from '@/types'
import { CIRCUIT_META, formatLatency, formatNumber, metaOf } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'

defineProps<{
  models: ModelHealthVO[]
  loading: boolean
  error: string
}>()

const emit = defineEmits<{ retry: [] }>()
</script>

<style scoped lang="scss">
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.model-card {
  padding: 14px 16px;
  background: #fff;
  border: 1px solid var(--ecom-border);
  border-left: 3px solid var(--ecom-success);
  border-radius: var(--ecom-radius, 10px);

  &.is-down {
    border-left-color: var(--ecom-danger);
  }

  &__head {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__dot {
    width: 8px;
    height: 8px;
    background: #cbd5e1;
    border-radius: 50%;

    &.is-ok {
      background: var(--ecom-success);
      box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15);
    }

    &.is-down {
      background: var(--ecom-danger);
    }
  }

  &__name {
    flex: 1;
    overflow: hidden;
    font-size: 13px;
    font-weight: 600;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__meta {
    margin: 4px 0 10px;
    font-size: 11px;
    color: var(--ecom-text-secondary);
  }

  &__stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 8px;
  }

  &__stat {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 10px;
    color: var(--ecom-text-secondary);

    strong {
      font-size: 13px;
      font-weight: 600;
      color: var(--ecom-text-primary);
    }
  }
}

.text-success {
  color: var(--ecom-success) !important;
}

.text-danger {
  color: var(--ecom-danger) !important;
}
</style>
