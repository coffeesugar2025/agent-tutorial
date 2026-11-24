<script setup lang="ts">
import { ref } from 'vue'
import { apiUrl } from '../api/backend'
const q = ref('退货政策')
const answer = ref('')
const citations = ref<{ ref: number; doc_id: string; chunk_id: string }[]>([])
const decision = ref('')
async function ask() {
  const r = await fetch(apiUrl('/v2/rag/query'), {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ question: q.value, mode: 'all', top_k: 3 }),
  })
  const d = await r.json()
  answer.value = d.answer || ''
  citations.value = d.citations || []
  decision.value = d.decision || 'allow'
}
</script>
<template>
  <section class="panel">
    <header><h3>引用溯源与幻觉控制</h3></header>
    <div class="ops"><input v-model="q" /><button @click="ask">检索作答</button></div>
    <p class="hint">事实后标 [n]，点开可回溯 doc_id / chunk_id；资料不足直接拒答。</p>
    <div v-if="answer" class="answer">{{ answer }}</div>
    <div v-for="c in citations" :key="c.ref" class="cite">
      [{{ c.ref }}] {{ c.doc_id }} · {{ c.chunk_id }}
    </div>
    <div v-if="decision && decision !== 'allow'" class="warn">安全决策：{{ decision }}</div>
  </section>
</template>
<style scoped>
.panel { border: 1px solid #e3e8f0; border-radius: 12px; padding: 16px; }
.ops { display: flex; gap: 8px; }
input { flex: 1; border: 1px solid #cbd7ee; border-radius: 6px; padding: 6px 10px; }
button { border: 1px solid #cbd7ee; background: #fff; border-radius: 6px; padding: 4px 12px; cursor: pointer; }
.hint, .cite { color: #667; font-size: 12px; }
.answer { background: #f7f9fc; padding: 10px; border-radius: 8px; margin: 10px 0; white-space: pre-wrap; }
.warn { color: #c33; font-size: 13px; }
</style>
