<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import StatusBadge from './components/StatusBadge.vue'
import SessionSidebar from './components/SessionSidebar.vue'
import MessageBubble from './components/MessageBubble.vue'
import Composer from './components/Composer.vue'
import { detectIntent, getHealth, getTools, streamChat } from './api/client'
import type {
  AgentCard, AgentEvent, ChatMessage, HealthInfo, Session, ToolInfo,
} from './types'

const QUICK_PROMPTS = [
  { q: '帮我找一下 500 元以内的降噪耳机', hint: '商品检索 + 价格过滤' },
  { q: '星野 Pro 用 FULL100 券后多少钱', hint: '优惠券叠加与到手价计算' },
  { q: 'EC20261118001 订单到哪了', hint: '订单状态与物流节点查询' },
  { q: 'EC20261105002 能退货吗', hint: '售后资格 + 政策双工具编排' },
  { q: '预算 500 推荐点东西', hint: '规则推荐 + 可用券展示' },
  { q: 'SKU-1001 还有货吗', hint: '实时库存查询' },
]

function uid(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

function makeSession(): Session {
  return { id: uid(), title: '新会话', createdAt: Date.now(), messages: [] }
}

const sessions = ref<Session[]>([makeSession()])
const activeId = ref(sessions.value[0].id)
const health = ref<HealthInfo | null>(null)
const tools = ref<ToolInfo[]>([])
const busy = ref(false)
const scrollEl = ref<HTMLElement | null>(null)
let controller: AbortController | null = null

const activeSession = computed(
  () => sessions.value.find((s) => s.id === activeId.value) ?? sessions.value[0],
)
const currentMessages = computed(() => activeSession.value.messages)

function scrollToBottom() {
  nextTick(() => {
    const el = scrollEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

onMounted(async () => {
  try {
    const [h, t] = await Promise.all([getHealth(), getTools()])
    health.value = h
    tools.value = t
  } catch {
    health.value = null
  }
})

function applyEvent(msg: ChatMessage, ev: AgentEvent) {
  switch (ev.event) {
    case 'token':
      msg.content += String(ev.data.text ?? '')
      break
    case 'tool_start':
      msg.traces.push({
        index: Number(ev.data.index ?? msg.traces.length + 1),
        name: String(ev.data.name ?? ''),
        args: (ev.data.args as Record<string, unknown>) ?? {},
        status: 'running',
      })
      break
    case 'tool_end': {
      const name = String(ev.data.name ?? '')
      const trace =
        [...msg.traces].reverse().find((t) => t.name === name && t.status === 'running') ??
        [...msg.traces].reverse().find((t) => t.status === 'running')
      if (trace) {
        trace.status = 'success'
        trace.summary = String(ev.data.summary ?? '')
      }
      break
    }
    case 'cards': {
      const list = ev.data.cards
      if (Array.isArray(list)) msg.cards.push(...(list as AgentCard[]))
      break
    }
    case 'error':
      msg.error = String(ev.data.message ?? '未知错误')
      break
    case 'done':
      msg.meta = {
        elapsed_ms: Number(ev.data.elapsed_ms ?? 0),
        tool_calls: Number(ev.data.tool_calls ?? 0),
      }
      break
  }
  scrollToBottom()
}

async function send(text: string) {
  const question = text.trim()
  if (!question || busy.value) return

  const session = activeSession.value
  if (session.messages.length === 0) session.title = question.slice(0, 18)

  session.messages.push({
    id: uid(), role: 'user', content: question, createdAt: Date.now(), traces: [], cards: [],
  })
  const assistant = reactive<ChatMessage>({
    id: uid(), role: 'assistant', content: '', createdAt: Date.now(),
    streaming: true, traces: [], cards: [],
  })
  session.messages.push(assistant)

  busy.value = true
  controller = new AbortController()
  scrollToBottom()

  // 意图识别与对话并行，失败不影响主流程
  detectIntent(question, session.id)
    .then((intent) => { assistant.intent = intent.intent })
    .catch(() => { /* 意图标签是增强信息，静默降级 */ })

  try {
    await streamChat(
      { message: question, thread_id: session.id, user_id: 'u_1001' },
      (ev) => applyEvent(assistant, ev),
      controller.signal,
    )
  } catch (err) {
    const error = err as Error
    if (error.name !== 'AbortError') assistant.error = `请求失败：${error.message}`
  } finally {
    assistant.streaming = false
    busy.value = false
    controller = null
    scrollToBottom()
  }
}

function stop() {
  controller?.abort()
}

function newSession() {
  const s = makeSession()
  sessions.value.unshift(s)
  activeId.value = s.id
  scrollToBottom()
}

function selectSession(id: string) {
  activeId.value = id
  scrollToBottom()
}
</script>

<template>
  <div class="app-shell">
    <SessionSidebar
      :sessions="sessions"
      :active-id="activeId"
      @select="selectSession"
      @create="newSession"
    />

    <main class="main">
      <header class="topbar">
        <div>
          <h1>小栈 · 电商智能体</h1>
          <p>LangChain 1.5 create_agent · MCP Tools · 工具调用全链路可视化</p>
        </div>
        <StatusBadge :health="health" :tool-count="tools.length" />
      </header>

      <div class="message-scroll" ref="scrollEl">
        <div class="message-wrap" v-if="currentMessages.length">
          <MessageBubble v-for="m in currentMessages" :key="m.id" :message="m" />
        </div>

        <div class="empty" v-else>
          <h2>你好，我是小栈 👋</h2>
          <p>
            我可以查商品、算到手价、追订单、判售后资格。所有事实都通过 MCP 工具实时查询，
            不会凭记忆编造价格与库存。点一个试试：
          </p>
          <div class="quick-grid">
            <button
              v-for="item in QUICK_PROMPTS"
              :key="item.q"
              class="quick-item"
              @click="send(item.q)"
            >
              {{ item.q }}
              <small>{{ item.hint }}</small>
            </button>
          </div>
        </div>
      </div>

      <Composer
        :busy="busy"
        :quick-prompts="QUICK_PROMPTS"
        @send="send"
        @stop="stop"
      />
    </main>
  </div>
</template>
