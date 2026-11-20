<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ApiError, api, createSessionId, errorMessage } from '../api'
import AppIcon from '../components/AppIcon.vue'
import IdentitySwitcher from '../components/playground/IdentitySwitcher.vue'
import ChatPanel from '../components/playground/ChatPanel.vue'
import TraceTab from '../components/playground/TraceTab.vue'
import CitationsTab from '../components/playground/CitationsTab.vue'
import MemoryTab from '../components/playground/MemoryTab.vue'
import ApprovalTab from '../components/playground/ApprovalTab.vue'

const IDENTITIES = [
  {
    employeeId: 'E1001',
    name: '张伟',
    role: '技术部 · 后端工程师',
    intro: '查年假余额、读制度、提交请假',
  },
  {
    employeeId: 'E1004',
    name: '赵敏',
    role: 'HR · 共享服务中心',
    intro: '查制度口径、处理审批',
  },
  {
    employeeId: 'E1010',
    name: '郑爽',
    role: '招聘 · 招聘专员',
    intro: '找候选人、安排面试',
  },
]

const IDENTITY_KEY = 'hr-agent-demo-identity'
const SESSION_KEY = 'hr-agent-demo-session'

function loadIdentity() {
  try {
    const saved = localStorage.getItem(IDENTITY_KEY)
    if (IDENTITIES.some((item) => item.employeeId === saved)) return saved
  } catch {
    // 隐私模式下 localStorage 可能不可用，退回默认身份。
  }
  return 'E1001'
}

function loadSessionId() {
  try {
    const saved = localStorage.getItem(SESSION_KEY)
    if (saved && saved.startsWith('s_')) return saved
  } catch {
    // 忽略存储异常，使用新会话。
  }
  return createSessionId()
}

function persistSession(id = sessionId.value) {
  try {
    localStorage.setItem(SESSION_KEY, id)
  } catch {
    // 存储不可用不影响当前会话。
  }
}

const identityId = ref(loadIdentity())
const currentIdentity = computed(
  () => IDENTITIES.find((item) => item.employeeId === identityId.value) || IDENTITIES[0],
)

const sessionId = ref(loadSessionId())
const messages = ref([])
const steps = ref([])
const citations = ref([])
const memory = ref(null)
const usage = ref(null)
const approval = ref(null)
const lastStatus = ref('')
const suggestions = ref([])

const sending = ref(false)
const sendError = ref('')
const lastAttempt = ref({ text: '', appendUser: true })

const approvalSubmitting = ref(false)
const approvalError = ref('')

const resetting = ref(false)
const resetNotice = ref('')
const resetError = ref('')
let resetTimer = null

const scenarios = ref([])
const scenariosLoading = ref(false)
const scenariosError = ref('')

const activeTab = ref('trace')
let messageCounter = 0

function uid() {
  messageCounter += 1
  return `m_${Date.now().toString(36)}_${messageCounter}`
}

function welcomeContent(identity = currentIdentity.value) {
  return `当前身份：${identity.name}（${identity.employeeId}）。可以点快捷场景，或直接提问。所有数据均为虚构演示数据，敏感操作会先进入审批。`
}

function welcomeMessage() {
  return { id: uid(), role: 'system', content: welcomeContent() }
}

messages.value = [welcomeMessage()]

const pendingApproval = computed(() =>
  approval.value && String(approval.value.status || 'pending').toLowerCase() === 'pending',
)

const tabs = computed(() => [
  { id: 'trace', label: '执行轨迹', icon: 'activity', count: steps.value.length },
  { id: 'citations', label: '引用来源', icon: 'quote', count: citations.value.length },
  { id: 'memory', label: '记忆', icon: 'chip', count: Array.isArray(memory.value?.facts) ? memory.value.facts.length : 0 },
  {
    id: 'approval',
    label: '待审批',
    icon: 'shield',
    count: pendingApproval.value ? 1 : 0,
    alert: pendingApproval.value,
  },
])

const sessionShort = computed(() =>
  sessionId.value.length > 18 ? `${sessionId.value.slice(0, 14)}…` : sessionId.value,
)

function normalizeApproval(raw) {
  if (!raw || typeof raw !== 'object') return null
  return {
    ...raw,
    id: raw.id || raw.approval_id || '',
    risk: String(raw.risk || 'low').toLowerCase(),
    status: String(raw.status || 'pending').toLowerCase(),
  }
}

function scrollToTab(tab) {
  activeTab.value = tab
}

function onTabKeydown(event) {
  const index = tabs.value.findIndex((tab) => tab.id === activeTab.value)
  if (index < 0) return
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
    event.preventDefault()
    const delta = event.key === 'ArrowRight' ? 1 : -1
    const next = (index + delta + tabs.value.length) % tabs.value.length
    activeTab.value = tabs.value[next].id
    requestAnimationFrame(() => {
      document.getElementById(`tab-${tabs.value[next].id}`)?.focus()
    })
  }
}

async function loadScenarios() {
  scenariosLoading.value = true
  scenariosError.value = ''
  try {
    const data = await api.getScenarios()
    const list = Array.isArray(data) ? data : data?.scenarios || data?.items || []
    scenarios.value = list.filter((item) => item && (item.label || item.message))
  } catch (error) {
    scenariosError.value = errorMessage(error)
  } finally {
    scenariosLoading.value = false
  }
}

function resetSession() {
  sessionId.value = createSessionId()
  persistSession()
  messages.value = [welcomeMessage()]
  steps.value = []
  citations.value = []
  memory.value = null
  usage.value = null
  approval.value = null
  lastStatus.value = ''
  suggestions.value = []
  sendError.value = ''
  lastAttempt.value = { text: '', appendUser: false }
  approvalError.value = ''
  activeTab.value = 'trace'
}

function changeIdentity(employeeId) {
  if (sending.value || resetting.value || employeeId === identityId.value) return
  identityId.value = employeeId
  try {
    localStorage.setItem(IDENTITY_KEY, employeeId)
  } catch {
    // 忽略存储异常。
  }
  resetSession()
}

/** 刷新页面后，从后端恢复当前会话的消息、记忆与待审批单。 */
async function restoreSession() {
  try {
    const data = await api.getSession(sessionId.value)
    const history = (Array.isArray(data?.messages) ? data.messages : []).filter(
      (item) => item && (item.role === 'user' || item.role === 'assistant') && item.content,
    )
    if (history.length) {
      messages.value = [
        welcomeMessage(),
        ...history.map((item) => ({ id: uid(), role: item.role, content: item.content })),
      ]
    }
    if (data?.memory && typeof data.memory === 'object') memory.value = data.memory
    if (data?.approval) {
      approval.value = normalizeApproval(data.approval)
      activeTab.value = 'approval'
    }
  } catch (error) {
    // 404 表示后端重启或会话已过期，保留新会话即可，不打扰用户。
    if (!(error instanceof ApiError && error.status === 404)) {
      console.warn('恢复会话失败：', errorMessage(error))
    }
  }
}

/** 重置后端演示数据（会话、审批、审计），成功后清空当前前端状态。 */
async function resetDemo() {
  if (resetting.value || sending.value || approvalSubmitting.value) return
  resetting.value = true
  resetError.value = ''
  resetNotice.value = ''
  clearTimeout(resetTimer)
  try {
    await api.resetDemo()
    resetSession()
    resetNotice.value = '演示数据已重置'
    resetTimer = setTimeout(() => {
      resetNotice.value = ''
    }, 4000)
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      resetError.value = '重置失败：后端尚未提供 POST /api/demo/reset（404），请确认后端版本后重试。'
    } else if (error instanceof ApiError && error.status === 405) {
      resetError.value = '重置失败：接口方法不被支持，请确认后端使用 POST /api/demo/reset。'
    } else {
      resetError.value = `重置失败：${errorMessage(error)}`
    }
  } finally {
    resetting.value = false
  }
}

async function useScenario(scenario) {
  if (sending.value || resetting.value) return
  if (scenario.employee_id && scenario.employee_id !== identityId.value) {
    identityId.value = scenario.employee_id
    resetSession()
  }
  await send(scenario.message || scenario.label)
}

function applyResponse(response) {
  const responseSteps = Array.isArray(response?.steps) ? response.steps : []
  const responseCitations = Array.isArray(response?.citations) ? response.citations : []
  const responseUsage = response?.usage || null
  const totalMs = responseSteps.reduce((sum, step) => sum + (Number(step.duration_ms) || 0), 0)

  if (response?.session_id) {
    sessionId.value = response.session_id
    persistSession()
  }
  steps.value = responseSteps
  citations.value = responseCitations
  usage.value = responseUsage
  lastStatus.value = response?.status || ''
  if (response?.memory && typeof response.memory === 'object') memory.value = response.memory
  suggestions.value = Array.isArray(response?.suggestions)
    ? response.suggestions.filter((item) => typeof item === 'string' && item.trim())
    : []

  if (response?.approval) {
    approval.value = normalizeApproval(response.approval)
    activeTab.value = 'approval'
  }

  messages.value.push({
    id: uid(),
    role: 'assistant',
    content: response?.reply || '（后端未返回 reply 字段）',
    meta: {
      status: response?.status || '',
      intent: response?.intent || '',
      traceId: response?.trace_id || '',
      stepsCount: responseSteps.length,
      citationsCount: responseCitations.length,
      usage: responseUsage,
      totalMs,
      approval: response?.approval ? normalizeApproval(response.approval) : null,
    },
  })
}

async function send(text, { appendUser = true } = {}) {
  const message = String(text || '').trim()
  if (!message || sending.value) return

  sendError.value = ''
  lastAttempt.value = { text: message, appendUser }
  if (appendUser) {
    messages.value.push({ id: uid(), role: 'user', content: message })
  }

  sending.value = true
  try {
    const response = await api.chat({
      sessionId: sessionId.value,
      message,
      employeeId: identityId.value,
    })
    applyResponse(response)
  } catch (error) {
    sendError.value = errorMessage(error)
  } finally {
    sending.value = false
  }
}

function retrySend() {
  if (!lastAttempt.value.text || sending.value) return
  send(lastAttempt.value.text, { appendUser: false })
}

async function handleDecision({ decision, comment }) {
  const current = approval.value
  if (!current || !pendingApproval.value || approvalSubmitting.value) return

  approvalSubmitting.value = true
  approvalError.value = ''
  try {
    const response = await api.decideApproval({
      approvalId: current.id,
      decision,
      comment,
      approver: identityId.value,
    })
    const finalStatus = response?.status || (decision === 'approve' ? 'approved' : 'rejected')
    approval.value = {
      ...current,
      status: finalStatus,
      result: response?.result || '',
      audit_id: response?.audit_id || '',
    }
    if (response?.session_id) {
      sessionId.value = response.session_id
      persistSession()
    }

    messages.value.push({
      id: uid(),
      role: 'assistant',
      content:
        response?.result ||
        (decision === 'approve' ? '审批已通过，操作已执行。' : '审批已拒绝，操作未执行。'),
      meta: {
        approvalResult: true,
        status: finalStatus,
        auditId: response?.audit_id || '',
        approvalId: response?.approval_id || current.id,
      },
    })
    activeTab.value = 'approval'
  } catch (error) {
    approvalError.value = errorMessage(error)
  } finally {
    approvalSubmitting.value = false
  }
}

onMounted(() => {
  restoreSession()
  loadScenarios()
})

onBeforeUnmount(() => {
  clearTimeout(resetTimer)
})
</script>

<template>
  <div class="page playground">
    <div class="container">
      <header class="pg-head">
        <div class="pg-head__copy">
          <span class="eyebrow">
            <AppIcon name="terminal" :size="14" />
            Workbench
          </span>
          <h1 class="pg-head__title">HR Agent 工作台</h1>
          <p class="pg-head__desc">
            选一个演示身份提问：查余额、读制度、找候选人都可以直接执行；调薪、安排面试等敏感操作会停下来等人签字。
            这里的身份只通过 <code>employee_id</code> 传递，生产环境必须换成 OIDC/JWT。
          </p>
        </div>
        <div class="pg-head__actions">
          <span class="session-chip" :title="sessionId">
            <AppIcon name="chip" :size="13" />
            <span class="session-chip__id">{{ sessionShort }}</span>
          </span>
          <button type="button" class="btn btn--secondary btn--sm" @click="resetSession">
            <AppIcon name="refresh" :size="14" />
            新会话
          </button>
        </div>
      </header>

      <div class="identity-bar">
        <IdentitySwitcher
          class="identity-bar__switcher"
          :identities="IDENTITIES"
          :value="identityId"
          :disabled="sending || resetting"
          @change="changeIdentity"
        />
        <div class="identity-bar__tools">
          <button
            type="button"
            class="btn btn--secondary btn--sm reset-demo-btn"
            :disabled="sending || resetting || approvalSubmitting"
            title="调用 POST /api/demo/reset，清空会话、审批与审计演示数据"
            @click="resetDemo"
          >
            <span v-if="resetting" class="spinner"></span>
            <AppIcon v-else name="refresh" :size="14" />
            {{ resetting ? '重置中…' : '重置演示数据' }}
          </button>
          <span class="identity-bar__note">清空会话与审批记录</span>
        </div>
      </div>

      <p v-if="resetNotice || resetError" class="reset-banner" :class="resetError ? 'reset-banner--error' : 'reset-banner--ok'" role="status">
        <AppIcon :name="resetError ? 'alert-circle' : 'check-circle'" :size="14" />
        <span>{{ resetError || resetNotice }}</span>
        <button v-if="resetError" type="button" class="reset-banner__action" @click="resetDemo">重试</button>
        <button v-else type="button" class="reset-banner__close" aria-label="关闭提示" @click="resetNotice = ''">
          <AppIcon name="close" :size="12" />
        </button>
      </p>

      <div class="identity-hint">
        <AppIcon name="info" :size="13" />
        <span>{{ currentIdentity.intro }}</span>
        <span class="identity-hint__sep" aria-hidden="true"></span>
        <span>切换身份会自动开启新会话</span>
      </div>

      <div class="pg-grid">
        <ChatPanel
          :messages="messages"
          :sending="sending"
          :error="sendError"
          :scenarios="scenarios"
          :scenarios-loading="scenariosLoading"
          :scenarios-error="scenariosError"
          :suggestions="suggestions"
          :identity="currentIdentity"
          @send="send"
          @retry="retrySend"
          @scenario="useScenario"
          @retry-scenarios="loadScenarios"
          @open-approval="scrollToTab('approval')"
        />

        <section class="pg-panel" aria-label="运行详情">
          <div
            class="tabs pg-tabs"
            role="tablist"
            aria-label="运行详情标签页"
            @keydown="onTabKeydown"
          >
            <button
              v-for="tab in tabs"
              :id="`tab-${tab.id}`"
              :key="tab.id"
              type="button"
              class="tab"
              :class="{ 'is-active': activeTab === tab.id, 'tab--alert': tab.alert }"
              role="tab"
              :aria-selected="activeTab === tab.id"
              :aria-controls="`panel-${tab.id}`"
              :tabindex="activeTab === tab.id ? 0 : -1"
              @click="activeTab = tab.id"
            >
              <AppIcon :name="tab.icon" :size="14" />
              {{ tab.label }}
              <span v-if="tab.count" class="tab__count">{{ tab.count }}</span>
            </button>
          </div>

          <div class="pg-panel__status">
            <span v-if="lastStatus" class="pg-panel__status-text">
              最近一次请求：
              <b>{{ lastStatus }}</b>
            </span>
            <span v-else class="pg-panel__status-text">尚未发起请求</span>
            <span class="pg-panel__status-hint">
              <AppIcon name="lock" :size="12" />
              引用与轨迹只读展示
            </span>
          </div>

          <div
            :id="`panel-${activeTab}`"
            class="pg-panel__body"
            role="tabpanel"
            :aria-labelledby="`tab-${activeTab}`"
            tabindex="0"
          >
            <TraceTab v-if="activeTab === 'trace'" :steps="steps" :status="lastStatus" :usage="usage" />
            <CitationsTab v-else-if="activeTab === 'citations'" :citations="citations" />
            <MemoryTab v-else-if="activeTab === 'memory'" :memory="memory" :usage="usage" />
            <ApprovalTab
              v-else
              :approval="approval"
              :submitting="approvalSubmitting"
              :error="approvalError"
              :approver-name="currentIdentity.name"
              :approver-id="currentIdentity.employeeId"
              @decide="handleDecision"
            />
          </div>
        </section>
      </div>

      <p class="pg-foot">
        工作台只用于教学演示：会话与审批默认存在后端内存中，重启后丢失；生产环境需接入持久化、审计哈希链与真实权限系统。
      </p>
    </div>
  </div>
</template>

<style scoped>
.pg-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}
.pg-head__copy { min-width: 0; }
.pg-head__title {
  margin: 6px 0 0;
  font-size: clamp(26px, 3vw, 34px);
  letter-spacing: -0.035em;
}
.pg-head__desc {
  margin: 8px 0 0;
  max-width: 62em;
  color: var(--text-3);
  font-size: 13.5px;
  line-height: 1.8;
}
.pg-head__desc code {
  font-family: var(--font-mono);
  font-size: 12px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--surface-3);
  color: var(--text-2);
}
.pg-head__actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.session-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  color: var(--text-3);
  font-size: 11.5px;
}
.session-chip svg { color: var(--brand); }
.session-chip__id { font-family: var(--font-mono); font-size: 10.5px; }

.identity-bar {
  display: flex;
  align-items: stretch;
  gap: 10px;
}
.identity-bar__switcher { flex: 1; min-width: 0; }
.identity-bar__tools {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: center;
  gap: 4px;
  flex: none;
}
.reset-demo-btn { white-space: nowrap; }
.identity-bar__note { color: var(--text-4); font-size: 9.5px; line-height: 1.4; }

.reset-banner {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 10px 0 0;
  padding: 7px 11px;
  border-radius: 8px;
  border: 1px solid var(--border);
  font-size: 11.5px;
  line-height: 1.6;
}
.reset-banner svg { flex: none; }
.reset-banner--ok {
  border-color: var(--success-border);
  background: var(--success-soft);
  color: #05603a;
}
.reset-banner--error {
  border-color: var(--danger-border);
  background: var(--danger-soft);
  color: #912018;
}
.reset-banner__action {
  margin-left: auto;
  padding: 1px 7px;
  border: 1px solid var(--danger-border);
  border-radius: 5px;
  background: #fff;
  color: var(--danger);
  font-size: 10.5px;
  font-weight: 600;
}
.reset-banner__action:hover { background: #fff6f5; }
.reset-banner__close {
  display: grid;
  place-items: center;
  margin-left: auto;
  width: 20px;
  height: 20px;
  border: 0;
  border-radius: 5px;
  background: transparent;
  color: inherit;
  opacity: 0.7;
}
.reset-banner__close:hover { background: rgba(5, 96, 58, 0.08); opacity: 1; }

.identity-hint {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 2px 14px;
  color: var(--text-4);
  font-size: 11.5px;
}
.identity-hint svg { color: var(--text-4); }
.identity-hint__sep { width: 3px; height: 3px; border-radius: 50%; background: var(--border-strong); }

.pg-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 0.98fr);
  gap: 18px;
  align-items: stretch;
}
.pg-grid > * {
  height: clamp(580px, calc(100vh - 336px), 820px);
  min-height: 0;
}
.pg-panel {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: #fff;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.pg-tabs { flex: none; padding-top: 2px; }
.pg-panel__status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  padding: 7px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  font-size: 10.5px;
  color: var(--text-4);
}
.pg-panel__status-text b {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-2);
  background: #fff;
  border: 1px solid var(--border);
  padding: 0 5px;
  border-radius: 4px;
}
.pg-panel__status-hint { display: inline-flex; align-items: center; gap: 4px; }
.pg-panel__body { flex: 1; min-height: 0; overflow-y: auto; outline: none; }
.pg-foot {
  margin: 16px 2px 0;
  color: var(--text-4);
  font-size: 11px;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .identity-bar { flex-direction: column; gap: 8px; }
  .identity-bar__tools {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    padding: 0 2px;
  }
  .identity-bar__note { order: 2; }
}
@media (max-width: 1000px) {
  .pg-grid { grid-template-columns: minmax(0, 1fr); }
  .pg-grid > * { height: auto; }
  .pg-grid > :first-child { height: 620px; }
  .pg-panel { max-height: 620px; }
  .pg-panel__body { min-height: 320px; }
}
@media (max-width: 620px) {
  .pg-head { margin-bottom: 14px; }
  .pg-grid { gap: 14px; }
  .pg-grid > :first-child { height: 600px; }
  .pg-panel { max-height: 600px; }
  .pg-head__actions { width: 100%; }
}
</style>
