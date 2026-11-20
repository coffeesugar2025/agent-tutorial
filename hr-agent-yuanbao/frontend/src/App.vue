<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { getHealth, getChapters, runDemo, approve } from './api'
import { FALLBACK_CHAPTERS, FALLBACK_GROUPS } from './chapters'
import ResultCard from './components/ResultCard.vue'
import TraceTimeline from './components/TraceTimeline.vue'
import StateBoard from './components/StateBoard.vue'
import MetricsPanel from './components/MetricsPanel.vue'

const chapters = ref(FALLBACK_CHAPTERS)
const groups = ref(FALLBACK_GROUPS)
const activeId = ref('ch01_loop')
const form = ref({})
const result = ref(null)
const loading = ref(false)
const error = ref('')
const health = ref(null)
const backendOk = ref(false)

const active = computed(() => chapters.value.find(c => c.id === activeId.value) || chapters.value[0])
const grouped = computed(() =>
  groups.value.map(g => ({ name: g, items: chapters.value.filter(c => c.group === g) })),
)

function resetForm() {
  const f = {}
  for (const field of active.value?.fields || []) f[field.key] = field.default ?? ''
  form.value = f
}

watch(activeId, () => { resetForm(); result.value = null; error.value = '' })
watch(() => active.value?.fields, resetForm)

onMounted(async () => {
  resetForm()
  try {
    health.value = await getHealth()
    backendOk.value = true
  } catch {
    backendOk.value = false
    error.value = '后端未连接：请在工程根目录执行 uvicorn backend.main:app --reload --port 8000'
  }
  try {
    const data = await getChapters()
    chapters.value = data.chapters
    groups.value = data.groups
    resetForm()
  } catch { /* 保留兜底目录 */ }
})

async function run() {
  loading.value = true
  error.value = ''
  try {
    result.value = await runDemo(activeId.value, form.value)
  } catch (e) {
    error.value = `运行失败：${e.message}`
  } finally {
    loading.value = false
  }
}

async function doApprove(action) {
  const cid = result.value?.hitl?.case_id || result.value?.state?.case_id
  if (!cid) return
  loading.value = true
  error.value = ''
  try {
    result.value = await approve(cid, action)
  } catch (e) {
    error.value = `审批失败：${e.message}`
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <div class="logo">HR</div>
        <div>
          <h1>HR Agent 教学控制台</h1>
          <p>Python 3.12 · LangChain / LangGraph · Vue 3 · 本地 Ollama ｜ 16 个循序渐进的独立 Demo</p>
        </div>
      </div>
      <div class="top-status">
        <span class="badge" :class="backendOk ? 'badge-green' : 'badge-red'">
          {{ backendOk ? '● 后端已连接' : '● 后端未连接' }}
        </span>
        <span class="badge" :class="health?.mode === 'ollama' ? 'badge-green' : 'badge-amber'">
          {{ health?.mode === 'ollama' ? 'Ollama ' + health.model : '离线演示模式' }}
        </span>
      </div>
    </header>

    <div class="layout">
      <aside class="sidebar">
        <div class="side-title">学习路线</div>
        <div v-for="g in grouped" :key="g.name" class="side-group">
          <div class="group-name">{{ g.name }}</div>
          <button v-for="c in g.items" :key="c.id" class="chapter-btn"
                  :class="{ active: c.id === activeId }" @click="activeId = c.id">
            <span class="ch-no">{{ String(c.no).padStart(2, '0') }}</span>
            <span class="ch-title">{{ c.title }}</span>
          </button>
        </div>
        <div class="side-foot">配套教程：docs/HR_Agent_从零到生产.md</div>
      </aside>

      <main class="main">
        <div class="chapter-head">
          <div class="ch-tag">第 {{ active.no }} 章 · {{ active.id }}</div>
          <h2>{{ active.title }}</h2>
          <p>{{ active.brief }}</p>
        </div>

        <section class="card form-card">
          <div class="card-head"><h3>运行参数</h3><span class="sub">由后端 /api/chapters 下发</span></div>
          <div class="form-grid">
            <label v-for="f in active.fields" :key="f.key" class="field">
              <span class="field-label">{{ f.label }}</span>
              <select v-if="f.type === 'select'" v-model="form[f.key]">
                <option v-for="o in f.options" :key="o.value" :value="o.value">{{ o.label }}</option>
              </select>
              <input v-else-if="f.type === 'number'" type="number" v-model="form[f.key]" />
              <input v-else type="text" v-model="form[f.key]" :placeholder="f.placeholder || ''" />
            </label>
            <div v-if="!active.fields?.length" class="empty">后端启动后会自动生成本章参数表单。</div>
          </div>
          <div class="form-actions">
            <button class="btn btn-primary" :disabled="loading || !backendOk" @click="run">
              {{ loading ? '运行中…' : '▶ 运行本章 Demo' }}
            </button>
            <button class="btn btn-ghost" :disabled="loading" @click="resetForm">重置参数</button>
            <span class="run-hint">运行方式等价于：python demos/{{ active.id }}/demo.py</span>
          </div>
        </section>

        <div v-if="error" class="alert">{{ error }}</div>

        <div class="results" v-if="result">
          <div class="span-2"><ResultCard :answer="result.answer" :mode="result.mode" :trace-id="result.trace_id" /></div>
          <div class="span-2"><MetricsPanel :metrics="result.metrics" :state="result.state" /></div>
          <StateBoard :state="result.state" :hitl="result.hitl" @approve="doApprove" />
          <TraceTimeline :steps="result.steps" />
        </div>
        <div v-else class="placeholder card">
          选择左侧章节 → 填写参数 → 运行。右侧会展示最终回答、Metrics、状态机与完整 Trace。
        </div>
      </main>
    </div>
  </div>
</template>
