<template>
  <el-drawer :model-value="visible" title="Trace 详情" size="620px" @update:model-value="onVisibleChange">
    <DataState :loading="loading" :error="error" :empty="!loading && !detail && !error" empty-text="暂未选择 trace" @retry="load">
      <div v-if="detail" class="trace-detail">
        <div class="trace-detail__head">
          <span class="trace-detail__id mono">{{ detail.trace.traceId }}</span>
          <el-tag size="small" :type="statusMeta.tone" effect="plain">{{ statusMeta.label }}</el-tag>
          <el-tag v-if="detail.replayable" size="small" type="success" effect="plain">可重放</el-tag>
        </div>

        <el-descriptions :column="3" border size="small" class="mt-12">
          <el-descriptions-item label="Agent">{{ metaOf(AGENT_META, detail.trace.agentType).label }}</el-descriptions-item>
          <el-descriptions-item label="会话">{{ detail.trace.sessionId ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="步骤">{{ detail.trace.stepCount }}</el-descriptions-item>
          <el-descriptions-item label="总耗时">{{ formatLatency(detail.trace.totalLatencyMs) }}</el-descriptions-item>
          <el-descriptions-item label="总成本">{{ formatCents(detail.trace.totalCostCents) }}</el-descriptions-item>
          <el-descriptions-item label="Span 数">{{ detail.spans.length }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="trace-detail__section">Span 时间线</h4>
        <SpanTimeline :spans="detail.spans" />

        <h4 class="trace-detail__section">Span 列表</h4>
        <el-table :data="sortedSpans" size="small" border>
          <el-table-column prop="seq" label="#" width="50" align="right" />
          <el-table-column prop="name" label="名称" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="mono">{{ row.name }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="spanType" label="类型" width="80" />
          <el-table-column label="耗时" width="80" align="right">
            <template #default="{ row }">{{ formatLatency(row.latencyMs) }}</template>
          </el-table-column>
          <el-table-column prop="status" label="状态" width="80" />
        </el-table>
      </div>
    </DataState>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getTrace } from '@/api/admin'
import type { SpanVO, TraceDetailVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { AGENT_META, formatCents, formatLatency, metaOf, TRACE_STATUS_META } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import SpanTimeline from './SpanTimeline.vue'

const props = defineProps<{ visible: boolean; traceId: string }>()
const emit = defineEmits<{ 'update:visible': [visible: boolean] }>()

const detail = ref<TraceDetailVO | null>(null)
const loading = ref(false)
const error = ref('')

const statusMeta = computed(() => metaOf(TRACE_STATUS_META, detail.value?.trace.status))
const sortedSpans = computed<SpanVO[]>(() => [...(detail.value?.spans ?? [])].sort((a, b) => a.seq - b.seq))

async function load(): Promise<void> {
  if (!props.traceId) return
  loading.value = true
  error.value = ''
  try {
    detail.value = await getTrace(props.traceId)
  } catch (err) {
    error.value = errorMessage(err, 'Trace 详情加载失败')
    detail.value = null
  } finally {
    loading.value = false
  }
}

function onVisibleChange(value: boolean): void {
  emit('update:visible', value)
}

watch(
  () => [props.visible, props.traceId] as const,
  ([visible, traceId]) => {
    if (visible && traceId) void load()
  },
  { immediate: true },
)
</script>

<style scoped lang="scss">
.trace-detail {
  &__head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }

  &__id {
    font-size: 13px;
    font-weight: 600;
    word-break: break-all;
  }

  &__section {
    margin: 20px 0 10px;
    font-size: 14px;
    font-weight: 600;
  }
}
</style>
