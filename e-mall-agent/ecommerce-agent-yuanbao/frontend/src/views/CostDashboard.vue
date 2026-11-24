<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiUrl } from '../api/backend'
const report = ref<Record<string, any>>({})
const order = ref<{ priority: number; action: string }[]>([])
onMounted(async () => {
  const r = await fetch(apiUrl('/v3/cost/report'))
  const d = await r.json()
  report.value = d.report || {}
  order.value = d.optimization_order || []
})
</script>
<template>
  <section class="panel">
    <header><h3>成本看板</h3></header>
    <p class="hint">有效成本 = 单任务推理成本 / 成功率 + 人工兜底成本。</p>
    <div class="grid">
      <div><b>{{ report.spent_usd ?? '-' }}</b><span>已花费 USD</span></div>
      <div><b>{{ report.report?.effective_cost_usd ?? report.effective_cost_usd ?? '-' }}</b><span>有效成本</span></div>
      <div><b>{{ report.report?.per_success_task ?? report.per_success_task ?? '-' }}</b><span>每成功任务成本</span></div>
    </div>
    <h4>降本优先级</h4>
    <ol><li v-for="o in order" :key="o.priority">{{ o.action }}</li></ol>
  </section>
</template>
<style scoped>
.panel { border: 1px solid #e3e8f0; border-radius: 12px; padding: 16px; }
.hint { color: #667; font-size: 12px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 12px 0; }
.grid div { background: #f7f9fc; border-radius: 8px; padding: 12px; text-align: center; }
.grid b { display: block; font-size: 20px; color: #2b5cd9; }
.grid span, li { font-size: 12px; color: #667; }
</style>
