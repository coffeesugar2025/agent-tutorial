<template>
  <div class="page">
    <PageHeader title="可观测" description="运营指标、链路追踪、成本与模型健康（仅 ADMIN）">
      <el-select v-model="days" size="small" style="width: 112px" @change="reloadAnalytics">
        <el-option v-for="option in DAY_OPTIONS" :key="option" :label="`近 ${option} 天`" :value="option" />
      </el-select>
      <el-button size="small" type="primary" :loading="refreshing" @click="reloadAll">刷新</el-button>
    </PageHeader>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="概览" name="overview">
        <DataState
          :loading="overviewLoading"
          :error="overviewError"
          :empty="!overviewLoading && !overviewError && !overview"
          empty-text="暂无运营数据"
          empty-description="产生对话后即可看到指标"
          @retry="loadOverview"
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
              <MetricCard
                label="单次成功成本"
                :value="formatCents(overview.costPerSuccessCents)"
                hint="总成本 / 成功会话数"
              />
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

            <div class="obs-trend">
              <div class="panel">
                <div class="panel__header">
                  <span class="panel__title">会话趋势</span>
                  <span class="panel__subtitle">近 {{ days }} 天 · 按天</span>
                </div>
                <LineChart
                  :categories="trendDates"
                  :series="sessionSeries"
                  height="240px"
                  :value-formatter="formatNumber"
                />
              </div>

              <div class="panel">
                <div class="panel__header">
                  <span class="panel__title">成本趋势</span>
                  <span class="panel__subtitle">单位：分</span>
                </div>
                <LineChart
                  :categories="trendDates"
                  :series="costSeries"
                  height="240px"
                  :value-formatter="formatCents"
                />
              </div>
            </div>
          </template>
        </DataState>
      </el-tab-pane>

      <el-tab-pane label="链路" name="traces">
        <div class="panel">
          <div class="toolbar obs-toolbar">
            <el-select v-model="traceStatus" clearable placeholder="全部状态" style="width: 150px" @change="loadTraces">
              <el-option
                v-for="status in TRACE_STATUSES"
                :key="status"
                :label="metaOf(TRACE_STATUS_META, status).label"
                :value="status"
              />
            </el-select>
            <span class="text-muted">展示最近 20 条，点击行查看 span 时间线</span>
          </div>
          <TracePanel :traces="traces" :loading="tracesLoading" :error="tracesError" @select="openTrace" @refresh="loadTraces" />
        </div>
      </el-tab-pane>

      <el-tab-pane label="成本" name="costs">
        <CostPanel :costs="costs" :loading="costsLoading" :error="costsError" @retry="loadCosts" />
      </el-tab-pane>

      <el-tab-pane label="模型健康" name="models">
        <ModelPanel :models="models" :loading="modelsLoading" :error="modelsError" @retry="loadModels" />
      </el-tab-pane>
    </el-tabs>

    <TraceDrawer v-model:visible="traceDrawerVisible" :trace-id="activeTraceId" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getCosts, getModelHealth, getOverview, listTraces } from '@/api/admin'
import { TRACE_STATUSES, type CostVO, type ModelHealthVO, type OverviewVO, type TraceVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { formatCents, formatLatency, formatNumber, formatPercent, metaOf, TRACE_STATUS_META } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import LineChart from '@/components/chart/LineChart.vue'
import CostPanel from '@/components/observability/CostPanel.vue'
import ModelPanel from '@/components/observability/ModelPanel.vue'
import TraceDrawer from '@/components/observability/TraceDrawer.vue'
import TracePanel from '@/components/observability/TracePanel.vue'

const DAY_OPTIONS = [1, 7, 14, 30] as const

const days = ref<number>(7)
const activeTab = ref('overview')
const traceStatus = ref('')

const overview = ref<OverviewVO | null>(null)
const overviewLoading = ref(false)
const overviewError = ref('')

const traces = ref<TraceVO[]>([])
const tracesLoading = ref(false)
const tracesError = ref('')

const costs = ref<CostVO | null>(null)
const costsLoading = ref(false)
const costsError = ref('')

const models = ref<ModelHealthVO[]>([])
const modelsLoading = ref(false)
const modelsError = ref('')

const traceDrawerVisible = ref(false)
const activeTraceId = ref('')

const refreshing = computed(
  () => overviewLoading.value || tracesLoading.value || costsLoading.value || modelsLoading.value,
)

const trend = computed(() => overview.value?.trend ?? [])
const trendDates = computed(() => trend.value.map((point) => point.date))
const sessionSeries = computed(() => [
  { name: '会话数', data: trend.value.map((point) => point.sessions), area: true },
])
const costSeries = computed(() => [
  { name: '成本(分)', data: trend.value.map((point) => point.costCents), area: true },
])

async function loadOverview(): Promise<void> {
  overviewLoading.value = true
  overviewError.value = ''
  try {
    overview.value = await getOverview(days.value)
  } catch (err) {
    overviewError.value = errorMessage(err, '运营概览加载失败')
    overview.value = null
  } finally {
    overviewLoading.value = false
  }
}

async function loadTraces(): Promise<void> {
  tracesLoading.value = true
  tracesError.value = ''
  try {
    traces.value = await listTraces({
      status: traceStatus.value || undefined,
      limit: 20,
    })
  } catch (err) {
    tracesError.value = errorMessage(err, 'Trace 列表加载失败')
    traces.value = []
  } finally {
    tracesLoading.value = false
  }
}

async function loadCosts(): Promise<void> {
  costsLoading.value = true
  costsError.value = ''
  try {
    costs.value = await getCosts(days.value)
  } catch (err) {
    costsError.value = errorMessage(err, '成本数据加载失败')
    costs.value = null
  } finally {
    costsLoading.value = false
  }
}

async function loadModels(): Promise<void> {
  modelsLoading.value = true
  modelsError.value = ''
  try {
    models.value = await getModelHealth()
  } catch (err) {
    modelsError.value = errorMessage(err, '模型健康加载失败')
    models.value = []
  } finally {
    modelsLoading.value = false
  }
}

function reloadAnalytics(): void {
  void loadOverview()
  void loadCosts()
}

function reloadAll(): void {
  void loadOverview()
  void loadTraces()
  void loadCosts()
  void loadModels()
}

function openTrace(traceId: string): void {
  activeTraceId.value = traceId
  traceDrawerVisible.value = true
}

onMounted(reloadAll)
</script>

<style scoped lang="scss">
.obs-trend {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-top: 16px;
}

.obs-toolbar {
  margin-bottom: 4px;
}

@media (max-width: 1000px) {
  .obs-trend {
    grid-template-columns: 1fr;
  }
}
</style>
