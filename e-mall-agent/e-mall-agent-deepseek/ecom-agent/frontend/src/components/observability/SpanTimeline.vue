<template>
  <div class="span-timeline">
    <div class="span-timeline__legend">
      <span>按 seq 顺序推算时间轴（契约中 span 无绝对开始时间）</span>
      <span class="mono">共 {{ spans.length }} 个 span</span>
    </div>

    <div v-for="row in rows" :key="row.span.spanId" class="span-row">
      <div class="span-row__label">
        <span class="span-row__indent" :style="{ paddingLeft: `${row.depth * 16}px` }">
          <el-tag size="small" :type="metaOf(SPAN_TYPE_META, row.span.spanType).tone" effect="plain">
            {{ metaOf(SPAN_TYPE_META, row.span.spanType).label }}
          </el-tag>
          <span class="span-row__name mono" :title="row.span.name">{{ row.span.name }}</span>
        </span>
      </div>
      <div class="span-row__track">
        <div
          class="span-row__bar"
          :class="[`is-${row.span.status.toLowerCase()}`]"
          :style="{ left: `${row.left}%`, width: `${row.width}%` }"
          :title="`${row.span.name} · ${formatLatency(row.span.latencyMs)} · ${row.span.status}`"
        >
          <span class="span-row__bar-text">{{ formatLatency(row.span.latencyMs) }}</span>
        </div>
      </div>
      <div class="span-row__status">
        <span :class="row.span.status === 'ERROR' ? 'text-danger' : 'text-muted'">
          {{ row.span.status }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { SpanVO } from '@/types'
import { formatLatency, metaOf, SPAN_TYPE_META } from '@/utils/format'

interface SpanRow {
  span: SpanVO
  left: number
  width: number
  depth: number
}

const props = defineProps<{ spans: SpanVO[] }>()

const rows = computed<SpanRow[]>(() => {
  const sorted = [...props.spans].sort((a, b) => a.seq - b.seq)
  const total = sorted.reduce((sum, span) => sum + Math.max(0, span.latencyMs || 0), 0) || 1
  let cursor = 0
  return sorted.map((span) => {
    const latency = Math.max(0, span.latencyMs || 0)
    const left = (cursor / total) * 100
    cursor += latency
    return {
      span,
      left,
      width: Math.max((latency / total) * 100, 0.8),
      depth: span.parentSpanId ? 1 : 0,
    }
  })
})
</script>

<style scoped lang="scss">
.span-timeline {
  &__legend {
    display: flex;
    justify-content: space-between;
    margin-bottom: 8px;
    font-size: 11px;
    color: var(--ecom-text-secondary);
  }
}

.span-row {
  display: grid;
  grid-template-columns: 240px 1fr 64px;
  gap: 10px;
  align-items: center;
  padding: 3px 0;
  font-size: 11.5px;

  &__indent {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 0;
  }

  &__name {
    overflow: hidden;
    color: var(--ecom-text-primary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__track {
    position: relative;
    height: 16px;
    background: #f1f5f9;
    border-radius: 4px;
  }

  &__bar {
    position: absolute;
    top: 1px;
    bottom: 1px;
    display: flex;
    align-items: center;
    padding: 0 4px;
    overflow: hidden;
    color: #fff;
    background: var(--ecom-primary);
    border-radius: 3px;
    cursor: default;

    &.is-ok {
      background: #3b82f6;
    }

    &.is-error {
      background: var(--ecom-danger);
    }

    &.is-running {
      background: var(--ecom-warning);
    }

    &-text {
      overflow: hidden;
      font-size: 9.5px;
      white-space: nowrap;
    }
  }

  &__status {
    font-size: 10px;
    text-align: right;
  }
}

.text-danger {
  color: var(--ecom-danger);
}
</style>
