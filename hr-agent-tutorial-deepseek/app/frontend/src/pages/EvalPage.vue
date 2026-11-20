<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, errorMessage } from '../api'
import AppIcon from '../components/AppIcon.vue'
import MetricCard from '../components/eval/MetricCard.vue'
import BaselineCompare from '../components/eval/BaselineCompare.vue'
import CaseTable from '../components/eval/CaseTable.vue'
import BadCaseList from '../components/eval/BadCaseList.vue'
import ErrorState from '../components/ui/ErrorState.vue'

const result = ref(null)
const running = ref(false)
const error = ref('')
const lastRunAt = ref(null)
const filter = ref('all')
const query = ref('')

function ratio(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  return number > 1 ? number / 100 : number
}

function formatPercent(value) {
  const number = ratio(value)
  return number === null ? '—' : `${(number * 100).toFixed(1)}%`
}

function formatMs(value) {
  const number = Number(value)
  return Number.isFinite(number) ? `${Math.round(number)}` : '—'
}

function formatNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '—'
}

function formatCost(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return '—'
  return number < 0.01 ? number.toFixed(6) : number.toFixed(4)
}

function ppDelta(current, base) {
  const now = ratio(current)
  const before = ratio(base)
  if (now === null || before === null) return null
  const diff = now - before
  return {
    text: `${diff >= 0 ? '+' : ''}${(diff * 100).toFixed(1)} pp`,
    direction: diff === 0 ? 'flat' : diff > 0 ? 'up' : 'down',
    good: diff > 0,
  }
}

function msDelta(current, base) {
  const now = Number(current)
  const before = Number(base)
  if (!Number.isFinite(now) || !Number.isFinite(before)) return null
  const diff = now - before
  return {
    text: `${diff >= 0 ? '+' : ''}${Math.round(diff)} ms`,
    direction: diff === 0 ? 'flat' : diff > 0 ? 'up' : 'down',
    good: diff < 0,
  }
}

const summary = computed(() => result.value?.summary || {})
const baseline = computed(() => result.value?.baseline || null)
const cases = computed(() => (Array.isArray(result.value?.cases) ? result.value.cases : []))
const failedCases = computed(() => cases.value.filter((item) => !item.passed))
const passedCount = computed(() => cases.value.filter((item) => item.passed).length)
const totalCount = computed(() => Number(summary.value.total) || cases.value.length)
const hasData = computed(() => Boolean(result.value))

const metrics = computed(() => {
  const data = summary.value
  const base = baseline.value || {}
  return [
    {
      key: 'success',
      label: '任务成功率',
      value: formatPercent(data.success_rate),
      icon: 'target',
      tone: 'success',
      hint: `通过 ${data.passed ?? passedCount.value} / ${data.total ?? totalCount.value} 条用例`,
      delta: ppDelta(data.success_rate, base.success_rate),
    },
    {
      key: 'tool',
      label: '工具准确率',
      value: formatPercent(data.tool_accuracy),
      icon: 'tool',
      tone: 'brand',
      hint: '工具集合与参数是否命中预期',
      delta: ppDelta(data.tool_accuracy, base.tool_accuracy),
    },
    {
      key: 'citation',
      label: '引用准确率',
      value: formatPercent(data.citation_accuracy),
      icon: 'quote',
      tone: 'violet',
      hint: '引用是否支撑结论且为最新版本',
      delta: null,
    },
    {
      key: 'p95',
      label: 'P95 延迟',
      value: formatMs(data.p95_latency_ms),
      unit: 'ms',
      icon: 'timer',
      tone: 'warning',
      hint: `平均 ${formatMs(data.avg_latency_ms)} ms · 不含网络`,
      delta: msDelta(data.p95_latency_ms, base.p95_latency_ms),
    },
    {
      key: 'cost',
      label: '评测总成本',
      value: `$${formatCost(data.cost_usd)}`,
      icon: 'dollar',
      tone: 'slate',
      hint: `累计 ${formatNumber(data.total_tokens)} tokens`,
      delta: null,
    },
  ]
})

const filteredCases = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return cases.value.filter((item) => {
    if (filter.value === 'failed' && item.passed) return false
    if (filter.value === 'passed' && !item.passed) return false
    if (!keyword) return true
    const haystack = `${item.id} ${item.input} ${(item.failures || []).join(' ')}`.toLowerCase()
    return haystack.includes(keyword)
  })
})

const emptyFilterMessage = computed(() => {
  if (query.value.trim()) return `没有匹配「${query.value.trim()}」的用例。`
  if (filter.value === 'failed') return '本次没有失败用例。'
  if (filter.value === 'passed') return '本次没有通过的用例。'
  return '没有用例数据。'
})

const runTimeText = computed(() => {
  if (!lastRunAt.value) return ''
  return lastRunAt.value.toLocaleTimeString('zh-CN', { hour12: false })
})

async function runEval() {
  if (running.value) return
  running.value = true
  error.value = ''
  try {
    const data = await api.runEval()
    if (!data || !data.summary || !Array.isArray(data.cases)) {
      throw new Error('评测接口返回结构不符合契约（缺少 summary 或 cases）。')
    }
    result.value = data
    lastRunAt.value = new Date()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    running.value = false
  }
}

onMounted(() => {
  runEval()
})
</script>

<template>
  <div class="page eval-page">
    <div class="container">
      <header class="eval-head">
        <div class="eval-head__copy">
          <span class="eyebrow">
            <AppIcon name="chart" :size="14" />
            Evaluation
          </span>
          <h1 class="eval-head__title">评测看板</h1>
          <p class="eval-head__desc">
            用 20 条 Golden Case 证明 Agent 变好了还是变差了：成功率、工具准确率、引用准确率、P95 延迟与成本，
            再和 baseline 做一次回归门禁对比。
          </p>
          <div class="eval-head__chips">
            <span class="chip chip--xs">20 条 Golden Case</span>
            <span class="chip chip--xs">确定性 · 离线</span>
            <span class="chip chip--xs">门槛：成功率下降 ≤ 2 pp</span>
          </div>
        </div>
        <div class="eval-head__actions">
          <button type="button" class="btn btn--primary" :disabled="running" @click="runEval">
            <span v-if="running" class="spinner spinner--light"></span>
            <AppIcon v-else name="refresh" :size="16" />
            {{ running ? '正在评测…' : hasData ? '重新运行评测' : '运行评测' }}
          </button>
          <span class="eval-head__time">
            <template v-if="runTimeText">
              <AppIcon name="clock" :size="12" />
              最近运行 {{ runTimeText }}
            </template>
            <template v-else>尚未运行</template>
          </span>
        </div>
      </header>

      <div v-if="running" class="run-indicator" role="status">
        <span class="run-indicator__bar"></span>
        <span>正在执行 20 条用例，统计意图、工具、必含内容与延迟…</span>
      </div>

      <!-- 首次加载骨架 -->
      <div v-if="running && !hasData" class="eval-skeleton" aria-busy="true">
        <div class="eval-skeleton__metrics">
          <div v-for="i in 5" :key="i" class="skeleton" style="height: 118px"></div>
        </div>
        <div class="skeleton" style="height: 220px; margin-top: 18px"></div>
        <div class="skeleton" style="height: 380px; margin-top: 18px"></div>
      </div>

      <!-- 失败态 -->
      <div v-else-if="error && !hasData" class="eval-error">
        <ErrorState
          title="评测运行失败"
          :message="error"
          retry-label="重新运行评测"
          :loading="running"
          @retry="runEval"
        />
        <p class="eval-error__hint">
          评测接口为 <code>POST /api/eval/run</code>，无请求体。请确认后端已实现该端点并返回 summary / baseline / cases。
        </p>
      </div>

      <!-- 空状态（自动运行前） -->
      <div v-else-if="!hasData" class="eval-empty">
        <div class="eval-empty__icon"><AppIcon name="chart" :size="26" /></div>
        <h2>还没有评测数据</h2>
        <p>点击运行，执行 20 条 Golden Case 并生成指标卡、用例表与 Bad Case 复盘。</p>
        <button type="button" class="btn btn--primary" :disabled="running" @click="runEval">
          <AppIcon name="play" :size="15" />
          运行评测
        </button>
      </div>

      <template v-else>
        <ErrorState
          v-if="error"
          compact
          class="eval-stale-error"
          title="最近一次评测失败，下方展示的是上一次成功结果"
          :message="error"
          retry-label="重试"
          :loading="running"
          @retry="runEval"
        />

        <section class="eval-metrics" aria-label="核心指标">
          <MetricCard
            v-for="metric in metrics"
            :key="metric.key"
            :label="metric.label"
            :value="metric.value"
            :unit="metric.unit || ''"
            :hint="metric.hint"
            :icon="metric.icon"
            :tone="metric.tone"
            :delta="metric.delta"
          />
        </section>

        <div class="eval-overview">
          <BaselineCompare :summary="summary" :baseline="baseline" />

          <section class="run-info card" aria-labelledby="run-info-title">
            <header class="run-info__head">
              <h2 id="run-info-title" class="run-info__title">本次运行</h2>
              <span class="chip chip--success chip--xs">completed</span>
            </header>
            <dl class="run-info__list">
              <div>
                <dt>用例总数</dt>
                <dd>{{ totalCount }}</dd>
              </div>
              <div>
                <dt>通过 / 失败</dt>
                <dd>{{ passedCount }} <span class="run-info__sep">/</span> {{ failedCases.length }}</dd>
              </div>
              <div>
                <dt>平均延迟</dt>
                <dd>{{ formatMs(summary.avg_latency_ms) }} ms</dd>
              </div>
              <div>
                <dt>总 tokens</dt>
                <dd>{{ formatNumber(summary.total_tokens) }}</dd>
              </div>
              <div>
                <dt>总成本</dt>
                <dd>${{ formatCost(summary.cost_usd) }}</dd>
              </div>
              <div>
                <dt>数据来源</dt>
                <dd class="run-info__mono">POST /api/eval/run</dd>
              </div>
            </dl>
            <p class="run-info__note">
              评测全部离线确定性执行，不调用外部模型；同一版本重复运行结果稳定，可用于回归门禁。
            </p>
          </section>
        </div>

        <section class="cases-section" aria-labelledby="cases-title">
          <div class="cases-head">
            <div>
              <h2 id="cases-title" class="cases-title">用例明细</h2>
              <p class="cases-subtitle">
                点击任意行查看 Agent 回复与失败原因；检查项分别为意图、工具集合、必含内容。
              </p>
            </div>
            <span class="chip chip--neutral chip--xs">{{ passedCount }} / {{ totalCount }} 通过</span>
          </div>

          <div class="case-toolbar">
            <div class="filter-group" role="group" aria-label="筛选用例">
              <button
                type="button"
                class="filter-btn"
                :class="{ 'is-active': filter === 'all' }"
                :aria-pressed="filter === 'all'"
                @click="filter = 'all'"
              >
                全部 <span>{{ cases.length }}</span>
              </button>
              <button
                type="button"
                class="filter-btn filter-btn--failed"
                :class="{ 'is-active': filter === 'failed' }"
                :aria-pressed="filter === 'failed'"
                @click="filter = 'failed'"
              >
                未通过 <span>{{ failedCases.length }}</span>
              </button>
              <button
                type="button"
                class="filter-btn"
                :class="{ 'is-active': filter === 'passed' }"
                :aria-pressed="filter === 'passed'"
                @click="filter = 'passed'"
              >
                已通过 <span>{{ passedCount }}</span>
              </button>
            </div>

            <label class="case-search">
              <AppIcon name="search" :size="14" />
              <span class="sr-only">搜索用例</span>
              <input v-model="query" type="search" placeholder="搜索编号、问题或失败原因" />
            </label>
          </div>

          <CaseTable :cases="filteredCases" :empty-message="emptyFilterMessage" />
        </section>

        <BadCaseList :cases="failedCases" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.eval-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.eval-head__copy { min-width: 0; }
.eval-head__title { margin: 6px 0 0; font-size: clamp(26px, 3vw, 34px); letter-spacing: -0.035em; }
.eval-head__desc {
  margin: 8px 0 0;
  max-width: 64em;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.8;
}
.eval-head__chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.eval-head__actions { display: flex; flex-direction: column; align-items: flex-end; gap: 7px; }
.eval-head__time {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--text-4);
  font-size: 10.5px;
}
.spinner--light { border-color: rgba(255, 255, 255, 0.35); border-top-color: #fff; }

.run-indicator {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 16px;
  padding: 9px 13px;
  border: 1px solid var(--brand-100);
  border-radius: 10px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-size: 12px;
  overflow: hidden;
}
.run-indicator__bar {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(79, 70, 229, 0.25);
  border-top-color: var(--brand);
  animation: spin 0.8s linear infinite;
  flex: none;
}

.eval-metrics {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 12px;
}
.eval-overview {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(0, 0.75fr);
  gap: 14px;
  margin-top: 18px;
  align-items: stretch;
}
.run-info { padding: 18px; display: flex; flex-direction: column; }
.run-info__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.run-info__title { margin: 0; font-size: 17px; letter-spacing: -0.015em; }
.run-info__list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0;
  margin: 12px 0 0;
  border-top: 1px solid var(--border);
}
.run-info__list > div {
  padding: 9px 0;
  border-bottom: 1px dashed var(--border);
}
.run-info__list > div:nth-child(odd) { padding-right: 12px; }
.run-info__list dt { color: var(--text-4); font-size: 10px; }
.run-info__list dd {
  margin: 2px 0 0;
  font-family: var(--font-mono);
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text);
}
.run-info__sep { color: var(--text-4); margin: 0 2px; }
.run-info__mono { font-size: 10px !important; color: var(--text-3) !important; }
.run-info__note {
  margin: auto 0 0;
  padding-top: 11px;
  color: var(--text-4);
  font-size: 10.5px;
  line-height: 1.7;
}

.cases-section { margin-top: 34px; }
.cases-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.cases-title { margin: 0; font-size: 18px; letter-spacing: -0.02em; }
.cases-subtitle { margin: 4px 0 0; color: var(--text-4); font-size: 11.5px; line-height: 1.65; }
.case-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.filter-group {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: #fff;
}
.filter-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: var(--text-3);
  font-size: 11.5px;
  font-weight: 600;
  transition: background-color 0.14s ease, color 0.14s ease;
}
.filter-btn span {
  font-family: var(--font-mono);
  font-size: 9.5px;
  padding: 0 4px;
  border-radius: 4px;
  background: var(--surface-3);
  color: var(--text-3);
  line-height: 1.7;
}
.filter-btn:hover { background: var(--surface-3); color: var(--text); }
.filter-btn.is-active { background: var(--brand); color: #fff; }
.filter-btn.is-active span { background: rgba(255, 255, 255, 0.2); color: #fff; }
.filter-btn--failed.is-active { background: var(--danger); }
.case-search {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  height: 32px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: #fff;
  color: var(--text-4);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.case-search:focus-within { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1); }
.case-search input {
  width: 210px;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--text);
  font-size: 11.5px;
  line-height: 1.6;
}
.case-search input::placeholder { color: var(--text-4); }
.case-search input::-webkit-search-cancel-button { cursor: pointer; }

.eval-skeleton__metrics { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; }
.eval-error__hint { margin: 12px 4px 0; color: var(--text-3); font-size: 12px; }
.eval-error__hint code {
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-3);
}
.eval-stale-error { margin-bottom: 16px; }
.eval-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 56px 20px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius);
  background: linear-gradient(180deg, #fff, var(--surface-2));
}
.eval-empty__icon {
  display: grid;
  place-items: center;
  width: 56px;
  height: 56px;
  border-radius: 16px;
  background: var(--brand-50);
  color: var(--brand);
}
.eval-empty h2 { margin: 14px 0 0; font-size: 18px; }
.eval-empty p { margin: 6px 0 18px; max-width: 32em; color: var(--text-3); font-size: 13px; line-height: 1.7; }

@media (max-width: 1180px) {
  .eval-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .eval-skeleton__metrics { grid-template-columns: repeat(3, 1fr); }
}
@media (max-width: 1000px) {
  .eval-overview { grid-template-columns: 1fr; }
}
@media (max-width: 720px) {
  .eval-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .eval-skeleton__metrics { grid-template-columns: repeat(2, 1fr); }
  .eval-head__actions { width: 100%; flex-direction: row; align-items: center; justify-content: space-between; }
  .case-search { width: 100%; }
  .case-search input { width: 100%; }
}
</style>
