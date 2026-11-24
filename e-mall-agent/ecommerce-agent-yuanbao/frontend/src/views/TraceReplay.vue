<script setup lang="ts">
import { ref } from 'vue'
import { apiUrl } from '../api/backend'
const traceId = ref('')
const frames = ref<Record<string, unknown>[]>([])
const diff = ref<Record<string, unknown>>({})
async function record() {
  const r = await fetch(apiUrl('/v3/replay/record'), {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question: '订单到哪了', prompt_version: 'v1' }),
  })
  const d = await r.json()
  traceId.value = d.trace_id
  frames.value = d.frames || []
}
async function replay() {
  const r = await fetch(apiUrl('/v3/replay/run'), {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ trace_id: traceId.value, overrides: {} }),
  })
  diff.value = await r.json()
}
</script>
<template>
  <section class="panel">
    <header><h3>轨迹回放与时间旅行</h3></header>
    <p class="hint">完整轨迹落盘 → 固定外部依赖确定性重放 → 回到第 N 步改写后重跑。</p>
    <div class="ops"><button @click="record">录制轨迹</button><button @click="replay" :disabled="!traceId">重放对比</button></div>
    <div v-if="traceId" class="tid">trace: {{ traceId }}</div>
    <ol><li v-for="(f, i) in frames" :key="i">{{ f.kind }} · {{ f.name }}</li></ol>
    <pre v-if="diff.ok">{{ JSON.stringify(diff, null, 2).slice(0, 600) }}</pre>
  </section>
</template>
<style scoped>
.panel { border: 1px solid #e3e8f0; border-radius: 12px; padding: 16px; }
.hint, .tid { color: #667; font-size: 12px; }
.ops { display: flex; gap: 8px; margin: 8px 0; }
button { border: 1px solid #cbd7ee; background: #fff; border-radius: 6px; padding: 4px 12px; cursor: pointer; }
pre { background: #f7f9fc; padding: 10px; border-radius: 8px; font-size: 12px; overflow: auto; }
</style>
