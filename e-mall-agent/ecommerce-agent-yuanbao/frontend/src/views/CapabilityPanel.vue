<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiUrl, detectBackend, BACKEND_LABEL, backend } from '../api/backend'
const info = ref<Record<string, unknown>>({})
const label = ref(BACKEND_LABEL[backend])
const error = ref('')
onMounted(async () => {
  try {
    const d = await detectBackend()
    label.value = `${d.backend} · ${d.framework || ''}`
    const r = await fetch(apiUrl('/v3/capabilities'))
    info.value = await r.json()
  } catch (e) { error.value = String(e) }
})
</script>
<template>
  <section class="panel">
    <header><h3>能力矩阵</h3><span class="badge">{{ label }}</span></header>
    <p class="hint">同一前端，两套后端共用契约；当前展示 {{ info.chapters || 10 }} 章知识点覆盖。</p>
    <div v-if="error" class="err">{{ error }}</div>
    <ul class="chapters">
      <li v-for="(v, k) in info" :key="String(k)"><b>{{ k }}</b><span>{{ String(v).slice(0, 90) }}</span></li>
    </ul>
  </section>
</template>
<style scoped>
.panel { border: 1px solid #e3e8f0; border-radius: 12px; padding: 16px; }
header { display: flex; justify-content: space-between; align-items: center; }
.badge { background: #eef4ff; color: #2b5cd9; padding: 4px 10px; border-radius: 999px; font-size: 12px; }
.hint { color: #667; font-size: 13px; }
.chapters { list-style: none; padding: 0; display: grid; gap: 8px; }
.chapters li { display: grid; grid-template-columns: 130px 1fr; gap: 8px; font-size: 13px; }
.chapters b { color: #2b5cd9; }
.err { color: #c33; }
</style>
