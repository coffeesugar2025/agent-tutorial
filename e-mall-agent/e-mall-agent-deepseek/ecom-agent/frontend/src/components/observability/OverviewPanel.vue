<template>
  <DataState
    :loading="loading"
    :error="error"
    :empty="!loading && !error && !overview"
    empty-text="暂无运营数据"
    @retry="emit('retry')"
  >
    <template v-if="overview">
      <div class="stat-grid">
        <MetricCard label="会话总数" :value="formatNumber(overview.totalSessions)" tone="primary" />
        <MetricCard label="消息总数" :value="formatNumber(overview.totalMessages)" />
        <MetricCard
          label="成功率"
          :value="formatPercent(overview.successRate)"
          :tone="overview.successRate >= 0.9 ? 'success' : 'warning'"
        />
        <MetricCard label="平均延迟" :value="formatLatency(overview.avgLatencyMs)" tone="warning" />
        <MetricCard label="P95 延迟" :value="formatLatency(overview.p95LatencyMs)" tone="warning" />
        <MetricCard label="总成本" :value="formatCents(overview.totalCostCents)" />
        <MetricCard label="单次成功成本" :value="formatCents(overview.costPerSuccessCents)" hint="总成本 / 成功会话数" />
        <MetricCard
          label="待审批"
          :value="formatNumber(overview.approvalPending)"
          :tone="overview.approvalPending > 0 ? 'danger' : 'success'"
        />
        <MetricCard
          label="工具错误率"
          :value="formatPercent(overview.toolErrorRate)"
          :tone="overview.toolErrorRate > 0.05 ? 'danger' : 'success'"
        />
      </div>

      <div class="overview__charts">
        <div class="panel">
          <div class="panel__header">
            <span class="panel__title">会话趋势</span>
            <span class="panel__subtitle">按天统计</span>
          </div>
          <LineChart
            :categories="trendDates"
            :series="sessionSeries"
            height="260px"
            :value-formatter="formatNumber"
          />
        </div>

        <div class="panel">
          <div class="panel__header">
            <span class="panel__title">工具调用 Top</span>
            <span class="panel__subtitle">调用次数</span>
          </div>
          <BarChart
            :categories="toolNames"
            :series="toolSeries"
            horizontal
            height="260px"
            :value-formatter="formatNumber"
          />
        </div>
      </div>
    </template>
  </DataState>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { OverviewVO } from '@/types'
import { formatCents, formatLatency, formatNumber, formatPercent } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import BarChart from '@/components/chart/BarChart.vue'
import LineChart from '@/components/chart/LineChart.vue'

const props = defineProps<{
  overview: OverviewVO | null
  loading: boolean
  error: string
}>()

const emit = defineEmits<{ retry: [] }>()

const trend = computed(() => props.overview?.trend ?? [])
const trendDates = computed(() => trend.value.map((point) => point.date))
const sessionSeries = computed(() => [
  { name: '会话数', data: trend.value.map((point) => point.sessions), area: true },
])

const topTools = computed(() => props.overview?.topTools ?? [])
const toolNames = computed(() => topTools.value.map((tool) => tool.name))
const toolSeries = computed(() => [{ name: '调用次数', data: topTools.value.map((tool) => tool.count) }])
</script>

<style scoped lang="scss">
.overview {
  &__charts {
    display: grid;
    grid-template-columns: 1.2fr 1fr;
    gap: 16px;
    margin-top: 16px;
  }
}

@media (max-width: 1000px) {
  .overview__charts {
    grid-template-columns: 1fr;
  }
}
</style>
