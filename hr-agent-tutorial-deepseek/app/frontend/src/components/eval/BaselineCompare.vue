<script setup>
import { computed } from 'vue'
import AppIcon from '../AppIcon.vue'

const props = defineProps({
  summary: { type: Object, default: () => ({}) },
  baseline: { type: Object, default: null },
})

function ratio(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  return number > 1 ? number / 100 : number
}

function formatPercent(value) {
  const number = ratio(value)
  return number === null ? '—' : `${(number * 100).toFixed(1)}%`
}

const rows = computed(() => {
  const base = props.baseline || {}
  return [
    {
      key: 'success',
      label: '任务成功率',
      current: ratio(props.summary.success_rate),
      base: ratio(base.success_rate),
      currentText: formatPercent(props.summary.success_rate),
      baseText: formatPercent(base.success_rate),
      lowerBetter: false,
      unit: 'pp',
    },
    {
      key: 'tool',
      label: '工具准确率',
      current: ratio(props.summary.tool_accuracy),
      base: ratio(base.tool_accuracy),
      currentText: formatPercent(props.summary.tool_accuracy),
      baseText: formatPercent(base.tool_accuracy),
      lowerBetter: false,
      unit: 'pp',
    },
    {
      key: 'p95',
      label: 'P95 延迟',
      current: Number.isFinite(Number(props.summary.p95_latency_ms)) ? Number(props.summary.p95_latency_ms) : null,
      base: Number.isFinite(Number(base.p95_latency_ms)) ? Number(base.p95_latency_ms) : null,
      currentText: Number.isFinite(Number(props.summary.p95_latency_ms)) ? `${props.summary.p95_latency_ms} ms` : '—',
      baseText: Number.isFinite(Number(base.p95_latency_ms)) ? `${base.p95_latency_ms} ms` : '—',
      lowerBetter: true,
      unit: 'ms',
    },
  ].filter((row) => row.base !== null)
})

function deltaOf(row) {
  if (row.current === null || row.base === null) return null
  if (row.unit === 'pp') {
    const diff = row.current - row.base
    return {
      text: `${diff >= 0 ? '+' : ''}${(diff * 100).toFixed(1)} pp`,
      good: row.lowerBetter ? diff < 0 : diff > 0,
      direction: diff === 0 ? 'flat' : diff > 0 ? 'up' : 'down',
    }
  }
  const diff = row.current - row.base
  return {
    text: `${diff >= 0 ? '+' : ''}${Math.round(diff)} ms`,
    good: row.lowerBetter ? diff < 0 : diff > 0,
    direction: diff === 0 ? 'flat' : diff > 0 ? 'up' : 'down',
  }
}

function barWidth(row) {
  if (row.current === null || row.base === null) return '0%'
  const max = Math.max(row.current, row.base) || 1
  return `${Math.round((row.current / max) * 100)}%`
}

function barBaseWidth(row) {
  if (row.current === null || row.base === null) return '0%'
  const max = Math.max(row.current, row.base) || 1
  return `${Math.round((row.base / max) * 100)}%`
}

const gate = computed(() => {
  const current = ratio(props.summary.success_rate)
  const base = ratio(props.baseline?.success_rate)
  if (current === null || base === null) return null
  const drop = base - current
  return {
    passed: drop <= 0.02,
    text:
      drop > 0.02
        ? `回归门禁未通过：成功率较 baseline 下降 ${(drop * 100).toFixed(1)} pp（阈值 2 pp）`
        : `回归门禁通过：成功率 ${drop >= 0 ? '较 baseline 低' : '较 baseline 高'} ${Math.abs(drop * 100).toFixed(1)} pp（阈值 2 pp）`,
  }
})
</script>

<template>
  <section class="baseline card" aria-labelledby="baseline-title">
    <header class="baseline__head">
      <div>
        <span class="eyebrow">Baseline</span>
        <h2 id="baseline-title" class="baseline__title">与上一版对比</h2>
      </div>
      <span class="chip chip--neutral chip--xs">旧 Prompt / 检索参数</span>
    </header>

    <div v-if="rows.length" class="baseline__rows">
      <div v-for="row in rows" :key="row.key" class="compare">
        <div class="compare__head">
          <span class="compare__label">{{ row.label }}</span>
          <span class="compare__values">
            <b>{{ row.currentText }}</b>
            <span class="compare__base">baseline {{ row.baseText }}</span>
          </span>
          <span
            v-if="deltaOf(row)"
            class="compare__delta"
            :class="deltaOf(row).direction === 'flat' ? 'is-flat' : deltaOf(row).good ? 'is-good' : 'is-bad'"
          >
            <AppIcon :name="deltaOf(row).direction === 'up' ? 'arrow-up-right' : deltaOf(row).direction === 'down' ? 'arrow-down-left' : 'minus'" :size="12" />
            {{ deltaOf(row).text }}
          </span>
        </div>
        <div class="compare__bars" aria-hidden="true">
          <span class="compare__bar compare__bar--base" :style="{ width: barBaseWidth(row) }"></span>
          <span class="compare__bar compare__bar--current" :style="{ width: barWidth(row) }"></span>
        </div>
      </div>
    </div>
    <p v-else class="baseline__empty">本次运行未返回 baseline 数据，无法对比历史版本。</p>

    <div v-if="gate" class="gate" :class="gate.passed ? 'gate--pass' : 'gate--fail'">
      <AppIcon :name="gate.passed ? 'check-circle' : 'alert-circle'" :size="15" />
      <span>{{ gate.text }}</span>
    </div>
  </section>
</template>

<style scoped>
.baseline { padding: 18px 18px 16px; }
.baseline__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.baseline__title { margin: 3px 0 0; font-size: 17px; letter-spacing: -0.015em; }
.baseline__rows { display: flex; flex-direction: column; gap: 15px; margin-top: 16px; }
.compare__head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.compare__label { font-size: 12px; color: var(--text-2); font-weight: 550; }
.compare__values { display: inline-flex; align-items: baseline; gap: 6px; margin-left: auto; }
.compare__values b { font-size: 14px; color: var(--text); letter-spacing: -0.02em; }
.compare__base { font-size: 10.5px; color: var(--text-4); }
.compare__delta {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 1px 6px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 650;
}
.compare__delta.is-good { color: var(--success); background: var(--success-soft); }
.compare__delta.is-bad { color: var(--danger); background: var(--danger-soft); }
.compare__delta.is-flat { color: var(--text-3); background: var(--surface-3); }
.compare__bars {
  position: relative;
  height: 8px;
  margin-top: 6px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
}
.compare__bar {
  position: absolute;
  top: 0;
  left: 0;
  height: 100%;
  border-radius: 999px;
  transition: width 0.5s ease;
}
.compare__bar--base { background: #cfd3e3; height: 100%; }
.compare__bar--current { background: linear-gradient(90deg, #6366f1, #8b5cf6); height: 100%; top: 0; opacity: 0.92; }
.compare__bar--base { opacity: 0.55; }
.gate {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 16px;
  padding: 9px 11px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  font-size: 11px;
  line-height: 1.65;
  color: var(--text-2);
}
.gate svg { flex: none; margin-top: 1px; }
.gate--pass { border-color: var(--success-border); background: var(--success-soft); color: #05603a; }
.gate--fail { border-color: var(--danger-border); background: var(--danger-soft); color: #912018; }
.baseline__empty { margin: 16px 0 0; color: var(--text-4); font-size: 12px; }
</style>
