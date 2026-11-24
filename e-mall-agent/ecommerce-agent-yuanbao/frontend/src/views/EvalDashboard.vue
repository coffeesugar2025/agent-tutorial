<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiUrl } from '../api/backend'
const data = ref<Record<string, unknown>>({})
const loading = ref(false)
async function run() {
  loading.value = true
  const r = await fetch(apiUrl('/v3/evals/stability'), {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ k: 3 }),
  })
  data.value = await r.json()
  loading.value = false
}
onMounted(run)
</script>
<template>
  <section class="panel">
    <header><h3>评测看板 · pass^k</h3><button @click="run">重跑</button></header>
    <p class="hint">pass^k（k 次全成功）才反映生产可用性；pass@k 只说明「至少一次成功」。</p>
    <div class="grid">
      <div><b>{{ data.aggregate_pass_pow_k ?? '-' }}</b><span>pass^k</span></div>
      <div><b>{{ data.aggregate_pass_at_k ?? '-' }}</b><span>pass@k</span></div>
      <div><b>{{ data.k ?? 3 }}</b><span>采样次数</span></div>
      <div><b>{{ (data.flaky_cases || []).length }}</b><span>不稳定用例</span></div>
    </div>
    <div v-if="loading" class="hint">评测中…</div>
  </section>
</template>
<style scoped>
.panel { border: 1px solid #e3e8f0; border-radius: 12px; padding: 16px; }
header { display: flex; justify-content: space-between; }
.hint { color: #667; font-size: 12px; }
.grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 12px; }
.grid div { background: #f7f9fc; border-radius: 8px; padding: 12px; text-align: center; }
.grid b { display: block; font-size: 22px; color: #2b5cd9; }
.grid span { font-size: 12px; color: #667; }
button { border: 1px solid #cbd7ee; background: #fff; border-radius: 6px; padding: 4px 12px; cursor: pointer; }
</style>
