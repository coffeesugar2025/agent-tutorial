<template>
  <DataState
    :loading="loading"
    :error="error"
    :empty="!loading && !error && !costs"
    empty-text="暂无成本数据"
    @retry="emit('retry')"
  >
    <template v-if="costs">
      <div class="stat-grid">
        <MetricCard label="总成本" :value="formatCents(costs.total)" tone="primary" />
        <MetricCard label="涉及模型" :value="costs.byModel.length" />
        <MetricCard label="供应商" :value="costs.byProvider.length" />
      </div>

      <div class="cost-grid">
        <div class="panel">
          <div class="panel__header">
            <span class="panel__title">成本按模型</span>
            <span class="panel__subtitle">占比</span>
          </div>
          <PieChart :items="modelItems" height="280px" :value-formatter="formatCents" />
        </div>

        <div class="panel">
          <div class="panel__header">
            <span class="panel__title">每日成本</span>
            <span class="panel__subtitle">单位：分</span>
          </div>
          <LineChart
            :categories="dailyDates"
            :series="dailySeries"
            height="280px"
            :value-formatter="formatCents"
          />
        </div>
      </div>

      <div class="panel cost-provider">
        <div class="panel__header">
          <span class="panel__title">按供应商</span>
        </div>
        <el-table :data="costs.byProvider" size="small" border>
          <el-table-column prop="provider" label="供应商" />
          <el-table-column label="成本" width="140" align="right">
            <template #default="{ row }">{{ formatCents(row.costCents) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </template>
  </DataState>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { CostVO } from '@/types'
import { formatCents } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import LineChart from '@/components/chart/LineChart.vue'
import PieChart from '@/components/chart/PieChart.vue'

const props = defineProps<{
  costs: CostVO | null
  loading: boolean
  error: string
}>()

const emit = defineEmits<{ retry: [] }>()

const modelItems = computed(() =>
  (props.costs?.byModel ?? []).map((item) => ({ name: item.model, value: item.costCents })),
)
const dailyDates = computed(() => (props.costs?.daily ?? []).map((item) => item.date))
const dailySeries = computed(() => [
  { name: '每日成本(分)', data: (props.costs?.daily ?? []).map((item) => item.costCents), area: true },
])
</script>

<style scoped lang="scss">
.cost-grid {
  display: grid;
  grid-template-columns: 1fr 1.2fr;
  gap: 16px;
  margin-top: 16px;
}

.cost-provider {
  margin-top: 16px;
}

@media (max-width: 1000px) {
  .cost-grid {
    grid-template-columns: 1fr;
  }
}
</style>
