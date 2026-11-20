<script setup>
import { computed } from 'vue'

const props = defineProps({
  metrics: { type: Object, default: () => ({}) },
  state: { type: Object, default: () => ({}) },
})

const LABELS = {
  llm_calls: 'LLM 调用', tool_calls: '工具调用', embed_calls: '向量化',
  tokens_est: 'Token 估算', duration_ms: '耗时 ms', retries: '重试',
  errors: '错误', cases_total: 'Case 总数', cases_passed: '通过', cases_failed: '失败',
}
const cards = computed(() => Object.entries(props.metrics || {}).filter(([, v]) => typeof v !== 'object'))
const before = computed(() => props.state?.before || null)
const after = computed(() => props.state?.after || null)
</script>

<template>
  <section class="card">
    <div class="card-head"><h3>Metrics / 评测</h3><span class="sub">本章运行指标</span></div>
    <div class="metric-grid">
      <div v-for="[k, v] in cards" :key="k" class="metric">
        <div class="metric-val">{{ typeof v === 'number' && !Number.isInteger(v) ? v.toFixed(2) : v }}</div>
        <div class="metric-key">{{ LABELS[k] || k }}</div>
      </div>
    </div>
    <div v-if="!cards.length" class="empty">暂无指标。</div>

    <div v-if="before && after" class="compare">
      <div class="compare-title">Golden Case 回归对比（Bad Case 修复前后）</div>
      <div class="compare-row"><span>阶段</span><span>任务成功率</span><span>工具命中率</span><span>P95 延迟</span></div>
      <div class="compare-row"><span>修复前</span><span>{{ before['任务成功率'] }}</span><span>{{ before['工具调用命中率'] }}</span><span>{{ before['P95 延迟(ms)'] }} ms</span></div>
      <div class="compare-row good"><span>修复后</span><span>{{ after['任务成功率'] }}</span><span>{{ after['工具调用命中率'] }}</span><span>{{ after['P95 延迟(ms)'] }} ms</span></div>
    </div>

    <div v-if="state.metrics && state.metrics.latency_ms" class="hist">
      延迟分布：count {{ state.metrics.latency_ms.count }} ｜
      avg {{ state.metrics.latency_ms.avg }} ms ｜
      P95 {{ state.metrics.latency_ms.p95 }} ms ｜ P99 {{ state.metrics.latency_ms.p99 }} ms
    </div>
  </section>
</template>
