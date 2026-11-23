<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  evaluateCases,
  hybridSearch,
  memoryRecall,
  metricsSnapshot,
  planGoal,
  sandboxRun,
  text2sql,
} from '../api/client'
import type {
  EvalReport,
  HybridResult,
  MemoryResult,
  MetricsSnapshot,
  PlanResult,
  SandboxResult,
  Text2SQLResult,
} from '../types'

type Tab = 'plan' | 'rag' | 'memory' | 'sandbox' | 'sql' | 'metrics' | 'eval'

const tabs: Array<{ key: Tab; label: string; desc: string }> = [
  { key: 'plan', label: '规划与推理', desc: 'ReAct / Plan-and-Solve' },
  { key: 'rag', label: '混合检索', desc: 'BM25 + 向量 + RRF' },
  { key: 'memory', label: '三层记忆', desc: '会话 / 情景 / 用户' },
  { key: 'sandbox', label: '代码沙箱', desc: 'AST 校验 / Code Mode' },
  { key: 'sql', label: 'Text2SQL', desc: '自然语言转受限查询' },
  { key: 'metrics', label: '运行指标', desc: '成功率 / 延迟 P95 / Token' },
  { key: 'eval', label: '评测体系', desc: 'Golden Case / 通过率' },
]

const active = ref<Tab>('plan')
const busy = ref(false)
const errorText = ref('')

const goal = ref('查询P001库存并下单1件')
const planMode = ref('plan_solve')
const planResult = ref<PlanResult | null>(null)

const ragQuery = ref('退款政策')
const ragMode = ref('hybrid')
const ragResult = ref<HybridResult | null>(null)

const memoryThread = ref('lab')
const memoryQuery = ref('耳机')
const memoryResult = ref<MemoryResult | null>(null)

const code = ref('result = 6 * 7\nprint(result)')
const sandboxMode = ref('plain')
const sandboxResult = ref<SandboxResult | null>(null)

const sqlQuestion = ref('列出所有商品')
const sqlResult = ref<Text2SQLResult | null>(null)
const metrics = ref<MetricsSnapshot | null>(null)
const evalReport = ref<EvalReport | null>(null)

onMounted(() => {
  void runMetrics()
})

async function guard(action: () => Promise<void>): Promise<void> {
  busy.value = true
  errorText.value = ''
  try {
    await action()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
  } finally {
    busy.value = false
  }
}

async function runPlan(): Promise<void> {
  await guard(async () => {
    planResult.value = await planGoal(goal.value, planMode.value as 'react' | 'plan_solve')
  })
}

async function runRag(): Promise<void> {
  await guard(async () => {
    ragResult.value = await hybridSearch(ragQuery.value, 5, ragMode.value)
  })
}

async function runMemory(): Promise<void> {
  await guard(async () => {
    memoryResult.value = await memoryRecall(memoryThread.value, memoryQuery.value)
  })
}

async function runSandbox(): Promise<void> {
  await guard(async () => {
    sandboxResult.value = await sandboxRun(code.value, sandboxMode.value as 'plain' | 'code_mode')
  })
}

async function runSql(): Promise<void> {
  await guard(async () => {
    sqlResult.value = await text2sql(sqlQuestion.value)
  })
}

async function runMetrics(): Promise<void> {
  await guard(async () => {
    metrics.value = await metricsSnapshot()
  })
}

async function runEval(): Promise<void> {
  await guard(async () => {
    const result = await evaluateCases([
      { id: 'c1', name: '问候', input: '你好', expected: { type: 'contains', value: '你好' }, tags: ['smoke'] },
      { id: 'c2', name: '商品', input: 'P001 无线降噪耳机', expected: { type: 'contains', value: 'P001' }, tags: ['smoke'] },
      { id: 'c3', name: '政策', input: '退款7天到账', expected: { type: 'contains', value: '退款' }, tags: ['policy'] },
    ])
    evalReport.value = result.report
  })
}
</script>

<template>
  <div class="lab">
    <div class="intro card">
      <div>
        <div class="section-title">能力实验室</div>
        <p class="muted small">直接调用后端新增的 Agent 能力，输入与输出实时可见。</p>
      </div>
      <div class="tags">
        <span class="badge badge-blue">Planning</span>
        <span class="badge badge-purple">RAG</span>
        <span class="badge badge-green">Memory</span>
        <span class="badge badge-amber">Sandbox</span>
      </div>
    </div>

    <div class="tabs">
      <button
        v-for="item in tabs"
        :key="item.key"
        type="button"
        class="tab"
        :class="{ active: active === item.key }"
        @click="active = item.key"
      >
        <span>{{ item.label }}</span>
        <small>{{ item.desc }}</small>
      </button>
    </div>

    <p v-if="errorText" class="error">{{ errorText }}</p>

    <!-- Planning -->
    <div v-if="active === 'plan'" class="card panel">
      <div class="panel-head">
        <div class="section-title">规划与推理</div>
        <span class="muted small">ReAct 循环 / Plan-and-Solve 拆解，带步数与超时终止条件</span>
      </div>
      <div class="form-row">
        <input v-model="goal" class="input" placeholder="输入目标，例如：查询P001库存并下单1件" />
        <select v-model="planMode" class="select mode-select">
          <option value="plan_solve">Plan-and-Solve</option>
          <option value="react">ReAct</option>
        </select>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="runPlan">执行</button>
      </div>
      <div v-if="planResult" class="result">
        <div class="result-head">
          <span class="badge badge-blue">{{ planResult.mode }}</span>
          <span class="badge">{{ planResult.terminated_reason || 'normal' }}</span>
        </div>
        <pre class="output">{{ planResult.answer }}</pre>
        <div class="trace">
          <div v-for="(step, index) in planResult.trace" :key="index" class="trace-item">
            <span class="step-no">{{ index + 1 }}</span>
            <span class="mono small">{{ JSON.stringify(step) }}</span>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">执行后展示答案与逐步轨迹</div>
    </div>

    <!-- Hybrid RAG -->
    <div v-if="active === 'rag'" class="card panel">
      <div class="panel-head">
        <div class="section-title">混合检索</div>
        <span class="muted small">BM25 全文召回 + 向量召回，RRF 融合并展示双通道来源明细</span>
      </div>
      <div class="form-row">
        <input v-model="ragQuery" class="input" placeholder="输入检索词，例如：退款政策" />
        <select v-model="ragMode" class="select mode-select">
          <option value="hybrid">Hybrid</option>
          <option value="bm25">BM25</option>
          <option value="vector">Vector</option>
        </select>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="runRag">检索</button>
      </div>
      <div v-if="ragResult" class="result">
        <div class="result-head"><span class="badge badge-purple">{{ ragResult.count }} 条命中</span></div>
        <div v-for="hit in ragResult.results" :key="hit.id" class="hit">
          <div class="hit-head">
            <span class="mono small">#{{ hit.rank }} {{ hit.id }}</span>
            <span class="badge">{{ hit.score.toFixed(5) }}</span>
          </div>
          <p class="small">{{ hit.content }}</p>
          <div class="sources">
            <span v-for="(source, key) in hit.sources" :key="key" class="badge badge-blue small">
              {{ key }} rank={{ source.rank }} raw={{ source.raw_score.toFixed(3) }}
            </span>
          </div>
        </div>
      </div>
      <div v-else class="empty-state">检索后展示融合结果与来源明细</div>
    </div>

    <!-- Memory -->
    <div v-if="active === 'memory'" class="card panel">
      <div class="panel-head">
        <div class="section-title">三层记忆</div>
        <span class="muted small">工作记忆 / 情景记忆 / 用户长期记忆，按 user_id 严格隔离</span>
      </div>
      <div class="form-row">
        <input v-model="memoryThread" class="input thread-input" placeholder="thread_id" />
        <input v-model="memoryQuery" class="input" placeholder="检索词" />
        <button class="btn btn-primary" type="button" :disabled="busy" @click="runMemory">召回</button>
      </div>
      <div v-if="memoryResult" class="result">
        <div class="result-head">
          <span class="badge badge-green">工作 {{ memoryResult.working.length }} 轮</span>
          <span class="badge badge-purple">情景 {{ memoryResult.episodes.length }} 条</span>
          <span class="badge badge-amber">约 {{ memoryResult.token_estimate }} tokens</span>
        </div>
        <pre class="output">{{ memoryResult.injected_context || '（暂无可注入记忆）' }}</pre>
      </div>
      <div v-else class="empty-state">召回后展示可注入 system prompt 的记忆上下文</div>
    </div>

    <!-- Sandbox -->
    <div v-if="active === 'sandbox'" class="card panel">
      <div class="panel-head">
        <div class="section-title">代码沙箱</div>
        <span class="muted small">AST 静态校验 + 受限执行；危险 import 与 dunder 属性会被拦截</span>
      </div>
      <div class="form-row">
        <select v-model="sandboxMode" class="select mode-select">
          <option value="plain">Plain</option>
          <option value="code_mode">Code Mode</option>
        </select>
        <button class="btn btn-primary" type="button" :disabled="busy" @click="runSandbox">执行</button>
      </div>
      <textarea v-model="code" class="textarea code-input" rows="5" spellcheck="false"></textarea>
      <div v-if="sandboxResult" class="result">
        <div class="result-head">
          <span class="badge" :class="sandboxResult.ok ? 'badge-green' : 'badge-red'">
            {{ sandboxResult.ok ? '成功' : '失败' }}
          </span>
          <span class="badge">{{ sandboxResult.duration_ms.toFixed(2) }} ms</span>
        </div>
        <pre class="output">stdout: {{ sandboxResult.stdout }}
value: {{ sandboxResult.value }}
error: {{ sandboxResult.error }}</pre>
      </div>
      <div v-else class="empty-state">执行后展示输出、返回值与耗时</div>
    </div>

    <!-- Text2SQL -->
    <div v-if="active === 'sql'" class="card panel">
      <div class="panel-head">
        <div class="section-title">Text2SQL</div>
        <span class="muted small">自然语言转受限 SELECT（禁止 DML、自动 LIMIT），在 SQLite 演示库执行</span>
      </div>
      <div class="form-row">
        <input v-model="sqlQuestion" class="input" placeholder="输入问题，例如：列出所有商品" />
        <button class="btn btn-primary" type="button" :disabled="busy" @click="runSql">查询</button>
      </div>
      <div v-if="sqlResult" class="result">
        <pre class="output">{{ sqlResult.sql }}</pre>
        <div class="result-head" style="margin-top: 10px">
          <span class="badge badge-blue">{{ sqlResult.rows.length }} 行</span>
          <span class="badge">{{ sqlResult.columns.join(' | ') }}</span>
        </div>
        <div v-for="(row, index) in sqlResult.rows.slice(0, 8)" :key="index" class="trace-item">
          <span class="mono small">{{ JSON.stringify(row) }}</span>
        </div>
      </div>
      <div v-else class="empty-state">查询后展示生成的 SQL 与结果行</div>
    </div>

    <!-- Metrics -->
    <div v-if="active === 'metrics'" class="card panel">
      <div class="panel-head">
        <div class="section-title">运行指标</div>
        <span class="muted small">来自真实对话链路的 Counter / Gauge / Histogram 埋点</span>
      </div>
      <button class="btn" type="button" :disabled="busy" @click="runMetrics">刷新指标</button>
      <div v-if="metrics" class="kpi-grid">
        <div class="kpi"><span>任务运行</span><strong>{{ metrics.summary.agent_runs }}</strong></div>
        <div class="kpi"><span>成功率</span><strong>{{ (metrics.summary.success_rate * 100).toFixed(1) }}%</strong></div>
        <div class="kpi"><span>工具调用</span><strong>{{ metrics.summary.tool_calls }}</strong></div>
        <div class="kpi"><span>Token 总量</span><strong>{{ metrics.summary.total_tokens }}</strong></div>
        <div class="kpi"><span>延迟 P95</span><strong>{{ metrics.summary.agent_latency_ms.p95.toFixed(1) }} ms</strong></div>
        <div class="kpi"><span>工具错误率</span><strong>{{ (metrics.summary.tool_error_rate * 100).toFixed(1) }}%</strong></div>
      </div>
      <div v-else class="empty-state">加载指标中...</div>
    </div>

    <!-- Eval -->
    <div v-if="active === 'eval'" class="card panel">
      <div class="panel-head">
        <div class="section-title">评测体系</div>
        <span class="muted small">Golden Case 批量评测，输出通过率、分组统计与延迟分位数</span>
      </div>
      <button class="btn btn-primary" type="button" :disabled="busy" @click="runEval">运行评测</button>
      <div v-if="evalReport" class="result">
        <div class="result-head">
          <span class="badge badge-green">{{ evalReport.passed }}/{{ evalReport.total }} 通过</span>
          <span class="badge badge-blue">{{ (evalReport.pass_rate * 100).toFixed(1) }}%</span>
          <span class="badge">P95 {{ evalReport.p95_latency_ms.toFixed(2) }} ms</span>
        </div>
        <div v-for="item in evalReport.per_case" :key="String(item.case_id)" class="trace-item">
          <span class="badge" :class="item.passed ? 'badge-green' : 'badge-red'">
            {{ item.passed ? 'PASS' : 'FAIL' }}
          </span>
          <span class="small">{{ String(item.name) || String(item.case_id) }}</span>
          <span class="mono small">score={{ Number(item.score).toFixed(2) }}</span>
        </div>
      </div>
      <div v-else class="empty-state">运行后展示 Golden Case 评测报告</div>
    </div>
  </div>
</template>

<style scoped>
.lab { display: flex; flex-direction: column; gap: 18px; }
.intro { padding: 18px 20px; display: flex; justify-content: space-between; align-items: center; }
.tags { display: flex; gap: 6px; flex-wrap: wrap; }
.tabs { display: flex; gap: 8px; flex-wrap: wrap; }
.tab {
  display: flex; flex-direction: column; gap: 2px; align-items: flex-start;
  padding: 10px 16px; border: 1px solid #e6e9ef; border-radius: 10px;
  background: #fff; cursor: pointer; min-width: 150px;
}
.tab:hover { background: #f8fafc; }
.tab.active { background: #ebf2ff; border-color: #bfd4ff; color: #1d4ed8; }
.tab span { font-size: 13.5px; font-weight: 600; }
.tab small { font-size: 11px; color: #9ca3af; }
.panel { padding: 20px; }
.panel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.form-row { display: flex; gap: 8px; margin-bottom: 14px; }
.mode-select { width: 170px; flex: 0 0 170px; }
.thread-input { width: 130px; flex: 0 0 130px; }
.code-input { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; resize: vertical; }
.result { border-top: 1px solid #eef0f4; padding-top: 14px; }
.result-head { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 10px; }
.output {
  background: #f8fafc; border: 1px solid #e6e9ef; border-radius: 8px;
  padding: 12px; margin: 0; white-space: pre-wrap; word-break: break-all;
  font-size: 12px; line-height: 1.6; max-height: 320px; overflow: auto;
}
.trace { margin-top: 12px; display: flex; flex-direction: column; gap: 6px; }
.trace-item { display: flex; gap: 8px; align-items: flex-start; padding: 7px 9px; background: #f8fafc; border-radius: 6px; }
.step-no {
  flex: 0 0 20px; height: 20px; border-radius: 50%; background: #e8f0ff;
  color: #1d4ed8; display: grid; place-items: center; font-size: 11px; font-weight: 600;
}
.hit { padding: 10px 0; border-bottom: 1px solid #eef0f4; }
.hit-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.sources { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 6px; }
.error { color: #c0392b; background: #feecea; border-radius: 8px; padding: 10px 12px; font-size: 13px; margin: 0; }
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin-top: 14px; }
.kpi { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; background: #f8fafc; border: 1px solid #e6e9ef; border-radius: 8px; }
.kpi span { font-size: 11px; color: #9ca3af; }
.kpi strong { font-size: 17px; color: #1f2937; }
</style>
