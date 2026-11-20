<script setup>
import { computed } from 'vue'

const props = defineProps({
  state: { type: Object, default: () => ({}) },
  hitl: { type: Object, default: null },
})
const emit = defineEmits(['approve'])

const stages = computed(() => Array.isArray(props.state?.stages) ? props.state.stages : null)
const entries = computed(() =>
  Object.entries(props.state || {})
    .filter(([k]) => k !== 'stages')
    .map(([k, v]) => ({ k, v, kind: v === null ? 'scalar' : Array.isArray(v) ? 'array' : typeof v === 'object' ? 'object' : 'scalar' })),
)

function columns(arr) {
  const first = arr.find(x => x && typeof x === 'object' && !Array.isArray(x))
  return first ? Object.keys(first).slice(0, 6) : []
}
function fmt(v) {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') { const s = JSON.stringify(v); return s.length > 160 ? s.slice(0, 160) + '…' : s }
  const s = String(v)
  return s.length > 200 ? s.slice(0, 200) + '…' : s
}
</script>

<template>
  <section class="card">
    <div class="card-head"><h3>状态与结构化数据</h3><span class="sub">state</span></div>

    <!-- 人工审批节点 -->
    <div v-if="hitl && hitl.required" class="hitl-box">
      <div class="hitl-title">⏸ Human-in-the-loop · 等待人工决策</div>
      <p>{{ hitl.prompt }}</p>
      <p class="hint">{{ hitl.sop }}</p>
      <div class="hitl-actions">
        <button v-for="a in hitl.actions" :key="a.key"
                class="btn" :class="a.key === 'reject' ? 'btn-danger' : 'btn-primary'"
                @click="emit('approve', a.key)">
          {{ a.label }}
        </button>
      </div>
      <p class="hint">case_id：{{ hitl.case_id }} ｜ 调用 POST /api/hitl/approve 从断点续跑</p>
    </div>

    <!-- 状态机步骤条 -->
    <div v-if="stages" class="stages">
      <div v-for="(s, i) in stages" :key="i" class="stage"
           :class="{ done: s.done, active: s.active }">
        <span class="stage-no">{{ i + 1 }}</span>
        <span class="stage-name">{{ s.name }}</span>
      </div>
    </div>

    <div v-if="!entries.length && !stages && !(hitl && hitl.required)" class="empty">本章没有额外的结构化状态。</div>

    <details v-for="e in entries" :key="e.k" class="state-block" :open="['status', 'summary', 'before', 'after', 'strategy', 'action'].includes(e.k)">
      <summary><span class="key-name">{{ e.k }}</span><span class="kind-tag">{{ e.kind }}</span></summary>

      <table v-if="e.kind === 'array' && columns(e.v).length" class="mini-table">
        <thead><tr><th v-for="c in columns(e.v)" :key="c">{{ c }}</th></tr></thead>
        <tbody>
          <tr v-for="(row, i) in e.v.slice(0, 12)" :key="i">
            <td v-for="c in columns(e.v)" :key="c">{{ fmt(row ? row[c] : '') }}</td>
          </tr>
        </tbody>
      </table>

      <ul v-else-if="e.kind === 'array'" class="kv-list">
        <li v-for="(row, i) in e.v.slice(0, 20)" :key="i">{{ fmt(row) }}</li>
      </ul>

      <div v-else-if="e.kind === 'object'" class="kv-grid">
        <div v-for="(val, key) in e.v" :key="key" class="kv-item">
          <span class="kv-key">{{ key }}</span><span class="kv-val">{{ fmt(val) }}</span>
        </div>
      </div>

      <div v-else class="scalar-val">{{ fmt(e.v) }}</div>
    </details>
  </section>
</template>
