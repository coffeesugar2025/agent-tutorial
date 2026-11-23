<template>
  <div class="trace-panel">
    <div class="toolbar trace-panel__toolbar">
      <span class="text-muted">最近 {{ traces.length }} 条 trace，点击行查看 span 时间线</span>
      <span class="toolbar__spacer" />
      <el-button size="small" :loading="loading" @click="emit('refresh')">刷新</el-button>
    </div>

    <DataState
      :loading="loading"
      :error="error"
      :empty="!loading && !error && traces.length === 0"
      empty-text="暂无 trace"
      empty-description="产生对话后即可查看链路"
      @retry="emit('refresh')"
    >
      <el-table :data="traces" size="small" @row-click="onRowClick">
        <el-table-column label="Trace" min-width="150">
          <template #default="{ row }">
            <span class="mono">{{ shortId(row.traceId) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="sessionId" label="会话" width="80" align="right" />
        <el-table-column label="Agent" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="metaOf(AGENT_META, row.agentType).tone" effect="plain">
              {{ metaOf(AGENT_META, row.agentType).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="metaOf(TRACE_STATUS_META, row.status).tone" effect="plain">
              {{ metaOf(TRACE_STATUS_META, row.status).label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90" align="right">
          <template #default="{ row }">{{ formatLatency(row.totalLatencyMs) }}</template>
        </el-table-column>
        <el-table-column label="成本" width="90" align="right">
          <template #default="{ row }">{{ formatCents(row.totalCostCents) }}</template>
        </el-table-column>
        <el-table-column prop="stepCount" label="步数" width="70" align="right" />
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
      </el-table>
    </DataState>
  </div>
</template>

<script setup lang="ts">
import type { TraceVO } from '@/types'
import {
  AGENT_META,
  TRACE_STATUS_META,
  formatCents,
  formatDateTime,
  formatLatency,
  metaOf,
} from '@/utils/format'
import DataState from '@/components/common/DataState.vue'

defineProps<{
  traces: TraceVO[]
  loading: boolean
  error: string
}>()

const emit = defineEmits<{ select: [traceId: string]; refresh: [] }>()

function shortId(traceId: string): string {
  return traceId.length > 12 ? `${traceId.slice(0, 12)}…` : traceId
}

function onRowClick(row: TraceVO): void {
  emit('select', row.traceId)
}
</script>

<style scoped lang="scss">
.trace-panel {
  &__toolbar {
    margin-bottom: 10px;
  }
}
</style>
