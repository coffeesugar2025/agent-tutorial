<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiUrl } from '../api/backend'
type Item = { id: string; summary: string; status: string; kind: string; trace_id: string }
const items = ref<Item[]>([])
const msg = ref('')
async function load() {
  const r = await fetch(apiUrl('/v2/approvals'))
  if (r.ok) { const d = await r.json(); items.value = d.pending || [] }
}
async function decide(id: string, decision: string) {
  const r = await fetch(apiUrl(`/v2/approvals/${id}/decide`), {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ decision, decided_by: 'reviewer' }),
  })
  msg.value = r.ok ? `${decision} 已提交` : '操作失败'
  await load()
}
onMounted(load)
</script>
<template>
  <section class="panel">
    <header><h3>人工审批中心</h3><button @click="load">刷新</button></header>
    <p class="hint">事前批准 / 事中打断 / 事后审核；超时默认拒绝。交接摘要自包含。</p>
    <div v-for="it in items" :key="it.id" class="card">
      <div class="kind">{{ it.kind }} · {{ it.trace_id }}</div>
      <p>{{ it.summary }}</p>
      <div class="ops">
        <button @click="decide(it.id, 'approve')">批准</button>
        <button @click="decide(it.id, 'reject')">拒绝</button>
        <button @click="decide(it.id, 'edit')">改写参数</button>
      </div>
    </div>
    <div v-if="!items.length" class="empty">当前无待审批项</div>
    <div v-if="msg" class="msg">{{ msg }}</div>
  </section>
</template>
<style scoped>
.panel { border: 1px solid #e3e8f0; border-radius: 12px; padding: 16px; }
header { display: flex; justify-content: space-between; }
.hint, .kind { color: #667; font-size: 12px; }
.card { border: 1px solid #e8edf5; border-radius: 8px; padding: 12px; margin: 10px 0; }
.ops { display: flex; gap: 8px; }
button { border: 1px solid #cbd7ee; background: #fff; border-radius: 6px; padding: 4px 12px; cursor: pointer; }
.msg { color: #2b5cd9; margin-top: 8px; }
.empty, .err { color: #889; font-size: 13px; }
</style>
