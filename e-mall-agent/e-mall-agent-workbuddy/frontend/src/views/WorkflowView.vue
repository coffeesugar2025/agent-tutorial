<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { graphs, resumeFulfillment, runFulfillment } from '../api/client'
import GraphFlow from '../components/GraphFlow.vue'
import type { FulfillmentResult, GraphBundle } from '../types'

const graphData = ref<GraphBundle | null>(null)
const loadingGraphs = ref(true)
const error = ref('')

const orderId = ref('O1001')
const threadId = ref('')
const resumeThreadId = ref('')
const approved = ref(true)
const result = ref<FulfillmentResult | null>(null)
const busy = ref(false)

async function loadGraphs(): Promise<void> {
  loadingGraphs.value = true
  error.value = ''
  try {
    graphData.value = await graphs()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '工作流图加载失败'
  } finally {
    loadingGraphs.value = false
  }
}

async function run(): Promise<void> {
  if (!orderId.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    result.value = await runFulfillment(orderId.value.trim(), threadId.value.trim() || undefined)
    if (result.value.interrupt) resumeThreadId.value = result.value.thread_id
  } catch (err) {
    error.value = err instanceof Error ? err.message : '运行履约流程失败'
  } finally {
    busy.value = false
  }
}

async function resume(): Promise<void> {
  if (!resumeThreadId.value.trim()) return
  busy.value = true
  error.value = ''
  try {
    result.value = await resumeFulfillment(resumeThreadId.value.trim(), approved.value)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '提交审批失败'
  } finally {
    busy.value = false
  }
}

onMounted(loadGraphs)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="section-title">工作流可视化</h2>
        <p class="small muted">查看多智能体路由与订单履约流程，并触发一次真实运行</p>
      </div>
      <button class="btn" type="button" :disabled="loadingGraphs" @click="loadGraphs">重新加载图</button>
    </div>

    <div v-if="error" class="notice error">{{ error }}</div>

    <div v-if="loadingGraphs" class="card empty-state">正在加载工作流定义...</div>
    <div v-else-if="graphData" class="graph-stack">
      <GraphFlow :graph="graphData.supervisor" />
      <GraphFlow :graph="graphData.fulfillment" />
    </div>

    <div class="controls-grid">
      <section class="card control-card">
        <h3 class="block-title">运行订单履约</h3>
        <p class="small muted">金额达到阈值的订单会在人工审批节点暂停，返回 thread_id 后可继续。</p>
        <label class="field">
          <span class="small muted">订单 ID</span>
          <input v-model="orderId" class="input" type="text" placeholder="例如 O1001" />
        </label>
        <label class="field">
          <span class="small muted">会话 ID（可选）</span>
          <input v-model="threadId" class="input" type="text" placeholder="留空则自动生成" />
        </label>
        <button class="btn btn-primary" type="button" :disabled="busy || !orderId.trim()" @click="run">
          {{ busy ? '执行中...' : '运行工作流' }}
        </button>
      </section>

      <section class="card control-card">
        <h3 class="block-title">人工审批恢复</h3>
        <p class="small muted">对处于等待审批状态的检查点提交批准或拒绝。</p>
        <label class="field">
          <span class="small muted">Thread ID</span>
          <input v-model="resumeThreadId" class="input" type="text" placeholder="运行返回的 thread_id" />
        </label>
        <div class="radio-row">
          <label><input v-model="approved" type="radio" :value="true" /> 批准</label>
          <label><input v-model="approved" type="radio" :value="false" /> 拒绝</label>
        </div>
        <button class="btn" type="button" :disabled="busy || !resumeThreadId.trim()" @click="resume">
          {{ busy ? '提交中...' : '提交审批' }}
        </button>
      </section>
    </div>

    <section v-if="result" class="card result-card">
      <div class="result-head">
        <h3 class="block-title">运行结果</h3>
        <span class="badge" :class="result.status === 'awaiting_approval' ? 'badge-amber' : result.status === 'completed' ? 'badge-green' : 'badge-blue'">
          {{ result.status }}
        </span>
      </div>
      <div class="result-summary">
        <span class="mono small">thread_id: {{ result.thread_id }}</span>
        <span class="small muted">{{ result.message }}</span>
      </div>

      <div v-if="result.interrupt" class="interrupt-box">
        <strong>等待人工审批</strong>
        <div class="small">类型: {{ result.interrupt.kind }} | 订单: {{ result.interrupt.order_id }} | 金额: ¥{{ result.interrupt.amount }}</div>
        <div class="small muted">{{ result.interrupt.reason }}</div>
      </div>

      <h4 class="block-title steps-title">执行步骤</h4>
      <ol class="timeline">
        <li v-for="(step, index) in result.steps" :key="index">
          <span class="step-index">{{ index + 1 }}</span>
          <span>{{ step }}</span>
        </li>
      </ol>
      <div v-if="result.steps.length === 0" class="empty-state">本次运行没有返回步骤</div>
    </section>
  </div>
</template>

<style scoped>
.page { max-width: 1180px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 18px; }
.page-head p { margin-top: 4px; }
.notice { padding: 10px 14px; border-radius: 8px; margin-bottom: 14px; font-size: 13px; }
.notice.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.graph-stack { display: flex; flex-direction: column; gap: 16px; margin-bottom: 18px; }
.controls-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; margin-bottom: 18px; }
.control-card { padding: 18px; display: flex; flex-direction: column; gap: 12px; }
.control-card p { line-height: 1.6; }
.field { display: flex; flex-direction: column; gap: 5px; }
.block-title { font-size: 14px; font-weight: 600; }
.radio-row { display: flex; gap: 18px; font-size: 13px; color: #374151; }
.radio-row label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
.result-card { padding: 18px; }
.result-head { display: flex; align-items: center; gap: 10px; }
.result-head .block-title { margin-bottom: 0; }
.result-summary { display: flex; flex-wrap: wrap; gap: 14px; margin: 10px 0 14px; }
.interrupt-box { padding: 11px 14px; border-radius: 8px; background: #fff8ea; border: 1px solid #f6dfae; color: #92400e; display: flex; flex-direction: column; gap: 4px; margin-bottom: 16px; }
.steps-title { margin-top: 14px; }
.timeline { list-style: none; padding: 0; margin: 0; }
.timeline li { display: flex; align-items: center; gap: 10px; padding: 8px 0; border-bottom: 1px dashed #e6e9ef; font-size: 13px; }
.timeline li:last-child { border-bottom: none; }
.step-index { width: 22px; height: 22px; flex: 0 0 22px; border-radius: 50%; background: #eaf1ff; color: #1d4ed8; display: grid; place-items: center; font-size: 11px; font-weight: 600; }
</style>
