<template>
  <div class="page">
    <PageHeader title="评测" description="选择 suite 与重复次数启动评测，轮询结果并查看 pass rate / pass^k" />

    <div class="panel">
      <div class="toolbar">
        <span class="eval-form__label">Suite</span>
        <el-select
          v-model="suite"
          filterable
          allow-create
          default-first-option
          placeholder="选择或输入评测集"
          style="width: 200px"
        >
          <el-option v-for="item in SUITES" :key="item" :label="item" :value="item" />
        </el-select>

        <span class="eval-form__label">重复次数</span>
        <el-input-number v-model="repeat" :min="1" :max="10" :step="1" />

        <el-button type="primary" :loading="starting" :disabled="!suite || running" @click="startRun">
          开始评测
        </el-button>
        <span class="toolbar__spacer" />
        <span v-if="polling" class="text-muted">评测运行中，每 2s 自动刷新…</span>
      </div>
      <p class="eval-form__hint">repeat 用于计算 pass^k：同一用例重复 k 次全部通过，才计入 k 次通过。</p>
    </div>

    <el-alert v-if="error" type="error" closable show-icon :title="error" @close="error = ''" />

    <template v-if="run">
      <div class="panel">
        <div class="panel__header">
          <span class="panel__title">运行 #{{ run.id }} · {{ run.suite }}</span>
          <el-tag size="small" :type="metaOf(EVAL_STATUS_META, run.status).tone" effect="plain">
            {{ metaOf(EVAL_STATUS_META, run.status).label }}
          </el-tag>
          <span class="toolbar__spacer" />
          <span class="text-muted">创建于 {{ formatDateTime(run.createdAt) }}</span>
        </div>

        <div class="eval-hero">
          <div class="eval-hero__item">
            <span class="eval-hero__label">Pass Rate</span>
            <strong class="eval-hero__value">{{ formatPercent(run.passRate) }}</strong>
            <span class="eval-hero__sub">{{ run.passed }} / {{ run.total }} 用例通过</span>
          </div>
          <div class="eval-hero__item">
            <span class="eval-hero__label">Pass^K</span>
            <strong class="eval-hero__value">{{ formatPercent(run.passK) }}</strong>
            <span class="eval-hero__sub">k = {{ activeRepeat }}（全部重复通过率）</span>
          </div>
        </div>

        <div class="stat-grid mt-12">
          <MetricCard label="用例总数" :value="formatNumber(run.total)" />
          <MetricCard label="通过数" :value="formatNumber(run.passed)" tone="success" />
          <MetricCard label="平均成本" :value="formatCents(run.avgCostCents)" />
          <MetricCard label="平均延迟" :value="formatLatency(run.avgLatencyMs)" tone="warning" />
        </div>
      </div>

      <div class="panel panel--flush">
        <div class="panel__header eval-cases__head">
          <span class="panel__title">用例结果</span>
          <span class="panel__subtitle">{{ cases.length }} 条 · 展开行查看期望 / 实际</span>
        </div>

        <DataState
          :loading="polling && cases.length === 0"
          :empty="!polling && cases.length === 0"
          empty-text="暂无用例结果"
          empty-description="评测运行中会持续轮询，完成后展示结果"
        >
          <el-table :data="cases" size="small" row-key="caseId">
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="eval-case-detail">
                  <p><span class="text-muted">期望：</span>{{ row.expected }}</p>
                  <p><span class="text-muted">实际：</span>{{ row.actual }}</p>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="caseId" label="用例" width="120" />
            <el-table-column prop="question" label="问题" min-width="260" show-overflow-tooltip />
            <el-table-column label="结果" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="row.passed ? 'success' : 'danger'" effect="plain">
                  {{ row.passed ? '通过' : '失败' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="分数" width="90" align="right">
              <template #default="{ row }">{{ formatScore(row.score) }}</template>
            </el-table-column>
          </el-table>
        </DataState>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getEvalRun, runEval } from '@/api/admin'
import type { EvalCaseVO, EvalRunStatus, EvalRunVO } from '@/types'
import {
  EVAL_STATUS_META, formatCents, formatDateTime, formatLatency, formatNumber, formatPercent, formatScore, metaOf,
} from '@/utils/format'
import { errorMessage } from '@/utils/guard'
import DataState from '@/components/common/DataState.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import PageHeader from '@/components/common/PageHeader.vue'

const SUITES = ['shopping', 'service', 'ops', 'knowledge', 'smoke']
const POLL_INTERVAL = 2000
const TERMINAL_STATUSES: EvalRunStatus[] = ['SUCCESS', 'FAILED', 'CANCELLED']

const suite = ref('shopping')
const repeat = ref<number | undefined>(3)
const activeRepeat = ref(1)
const starting = ref(false)
const polling = ref(false)
const error = ref('')
const run = ref<EvalRunVO | null>(null)

let timer: number | null = null

const cases = computed<EvalCaseVO[]>(() => run.value?.cases ?? [])
const running = computed(
  () => polling.value || run.value?.status === 'RUNNING' || run.value?.status === 'QUEUED',
)

function isTerminal(status: EvalRunStatus): boolean {
  return TERMINAL_STATUSES.includes(status)
}

function stopPolling(): void {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
  polling.value = false
}

async function pollOnce(runId: number): Promise<void> {
  try {
    const data = await getEvalRun(runId)
    run.value = data
    if (!isTerminal(data.status)) return
    stopPolling()
    if (data.status === 'SUCCESS') {
      ElMessage.success(`评测 #${data.id} 完成：通过率 ${formatPercent(data.passRate)}`)
    } else if (data.status === 'FAILED') {
      error.value = `评测 #${data.id} 执行失败，请检查后端日志后重试`
    }
  } catch (err) {
    stopPolling()
    error.value = errorMessage(err, '评测状态轮询失败')
  }
}

function startPolling(runId: number): void {
  stopPolling()
  polling.value = true
  timer = window.setInterval(() => void pollOnce(runId), POLL_INTERVAL)
  void pollOnce(runId)
}

async function startRun(): Promise<void> {
  const target = suite.value.trim()
  if (!target || starting.value || running.value) return
  starting.value = true
  error.value = ''
  run.value = null
  activeRepeat.value = repeat.value ?? 1
  try {
    const created = await runEval({ suite: target, repeat: activeRepeat.value })
    ElMessage.success(`评测 #${created.runId} 已提交（${created.status}）`)
    startPolling(created.runId)
  } catch (err) {
    error.value = errorMessage(err, '评测启动失败')
  } finally {
    starting.value = false
  }
}

onBeforeUnmount(stopPolling)
</script>

<style scoped lang="scss">
.eval-form__label {
  font-size: 13px;
  color: var(--ecom-text-secondary);
}

.eval-form__hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--ecom-text-secondary);
}

.eval-hero {
  display: flex;
  flex-wrap: wrap;
  gap: 40px;

  &__item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  &__label,
  &__sub {
    font-size: 12px;
    color: var(--ecom-text-secondary);
  }

  &__value {
    font-size: 42px;
    font-weight: 700;
    line-height: 1.15;
    color: var(--ecom-primary);
    font-variant-numeric: tabular-nums;
  }
}

.eval-cases__head {
  padding: 12px 16px;
  margin-bottom: 0;
  border-bottom: 1px solid var(--ecom-border);
}

.eval-case-detail {
  padding: 4px 16px 10px;
  font-size: 12px;

  p {
    margin: 4px 0;
    word-break: break-word;
  }
}
</style>
