<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { chatStream, contextPreview } from '../api/client'
import type { ChatEvent, ContextSnapshot, ToolCall } from '../types'

interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  route?: string
  tools: ToolCall[]
  nodes: string[]
  pending?: boolean
}

const route = useRoute()
const messages = ref<Message[]>([
  {
    id: 0,
    role: 'assistant',
    content: '您好，我是电商智能助手。可以帮我查找商品、管理订单或解答售后政策，试试下面的快捷问题。',
    tools: [],
    nodes: [],
  },
])
const input = ref('')
const threadId = ref('default')
const streaming = ref(false)
const error = ref('')
const listEl = ref<HTMLElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const contextOpen = ref(false)
const snapshot = ref<ContextSnapshot | null>(null)
const previewLoading = ref(false)

let messageId = 1

const quickPrompts = [
  '推荐一款降噪耳机',
  '查询我的订单状态',
  '退货政策是怎样的？',
  '帮我比较两款蓝牙耳机',
]

function prefillFromQuery(): void {
  const q = route.query.q
  if (typeof q === 'string' && q.trim()) {
    input.value = q
    nextTick(() => textareaEl.value?.focus())
  }
}

onMounted(prefillFromQuery)
watch(() => route.query.q, prefillFromQuery)

async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
}

function usePrompt(text: string): void {
  input.value = text
  nextTick(() => textareaEl.value?.focus())
}

function handleEvent(event: ChatEvent, assistant: Message): void {
  switch (event.event) {
    case 'node':
      if (!assistant.nodes.includes(event.node)) assistant.nodes.push(event.node)
      break
    case 'route':
      assistant.route = event.data
      break
    case 'context':
      snapshot.value = event.data
      break
    case 'tool':
      assistant.tools.push(event.data)
      break
    case 'token':
      assistant.content += event.data
      scrollToBottom()
      break
    case 'done':
      if (!assistant.content) assistant.content = event.data
      break
    case 'error':
      error.value = event.data
      break
  }
}

async function send(): Promise<void> {
  const text = input.value.trim()
  if (!text || streaming.value) return

  messages.value.push({ id: messageId++, role: 'user', content: text, tools: [], nodes: [] })
  const assistant: Message = { id: messageId++, role: 'assistant', content: '', tools: [], nodes: [], pending: true }
  messages.value.push(assistant)
  input.value = ''
  error.value = ''
  streaming.value = true
  await scrollToBottom()

  try {
    await chatStream(text, threadId.value || 'default', (event) => handleEvent(event, assistant))
  } catch (err) {
    error.value = err instanceof Error ? err.message : '请求失败，请稍后重试'
    if (!assistant.content) assistant.content = '抱歉，本次请求未能完成。'
  } finally {
    assistant.pending = false
    streaming.value = false
    await scrollToBottom()
  }
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

async function loadPreview(): Promise<void> {
  previewLoading.value = true
  error.value = ''
  try {
    snapshot.value = (await contextPreview(input.value.trim() || '我想买降噪耳机')).snapshot
    contextOpen.value = true
  } catch (err) {
    error.value = err instanceof Error ? err.message : '预览失败'
  } finally {
    previewLoading.value = false
  }
}
</script>

<template>
  <div class="chat-layout">
    <section class="card chat-main">
      <div class="chat-toolbar">
        <div class="toolbar-left">
          <span class="section-title">智能对话</span>
          <span class="badge badge-blue">SSE 实时流式</span>
        </div>
        <div class="toolbar-right">
          <label class="thread-field">
            <span class="small muted">会话 ID</span>
            <input v-model="threadId" class="input thread-input" type="text" :disabled="streaming" />
          </label>
          <button class="btn btn-sm" type="button" :disabled="previewLoading || streaming" @click="loadPreview">
            {{ previewLoading ? '生成中...' : '上下文预览' }}
          </button>
          <button class="btn btn-sm" type="button" @click="contextOpen = !contextOpen">
            {{ contextOpen ? '收起上下文' : '上下文工程' }}
          </button>
        </div>
      </div>

      <div ref="listEl" class="message-list">
        <div
          v-for="message in messages"
          :key="message.id"
          class="message-row"
          :class="message.role"
        >
          <div class="bubble" :class="message.role === 'user' ? 'bubble-user' : 'bubble-assistant'">
            <div class="bubble-head">
              <span class="speaker">{{ message.role === 'user' ? '我' : '智能助手' }}</span>
              <span v-if="message.route" class="badge badge-blue">路由: {{ message.route }}</span>
            </div>
            <div v-if="message.nodes.length" class="node-trail">
              <template v-for="(node, index) in message.nodes" :key="node">
                <span v-if="index > 0" class="trail-arrow">/</span>
                <span class="trail-node">{{ node }}</span>
              </template>
            </div>
            <div class="bubble-content" :class="{ empty: !message.content }">
              {{ message.content || (message.pending ? '正在思考...' : '') }}
              <span v-if="message.pending && message.content" class="caret"></span>
            </div>
            <div v-if="message.tools.length" class="tool-chips">
              <span v-for="(tool, index) in message.tools" :key="index" class="chip" :title="String(tool.content)">
                <span class="chip-dot"></span>{{ tool.name }}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div v-if="error" class="error-banner">{{ error }}</div>

      <div class="composer">
        <div class="quick-prompts">
          <span class="small muted">快捷提问</span>
          <button v-for="prompt in quickPrompts" :key="prompt" class="prompt-btn" type="button" @click="usePrompt(prompt)">
            {{ prompt }}
          </button>
        </div>
        <div class="composer-box">
          <textarea
            ref="textareaEl"
            v-model="input"
            class="textarea composer-input"
            rows="3"
            placeholder="输入您的问题，Enter 发送，Shift + Enter 换行"
            :disabled="streaming"
            @keydown="onKeydown"
          ></textarea>
          <div class="composer-foot">
            <span class="small muted">{{ streaming ? '助手正在回复...' : '基于商品、订单与知识库的真实数据回答' }}</span>
            <button class="btn btn-primary" type="button" :disabled="streaming || !input.trim()" @click="send">
              {{ streaming ? '生成中...' : '发送' }}
            </button>
          </div>
        </div>
      </div>
    </section>

    <aside v-if="contextOpen" class="card context-panel">
      <div class="panel-head">
        <div>
          <div class="section-title">上下文工程</div>
          <div class="small muted">实时上下文快照与裁剪结果</div>
        </div>
        <button class="btn btn-sm" type="button" @click="contextOpen = false">收起</button>
      </div>

      <div v-if="snapshot" class="panel-body">
        <div class="stats-grid">
          <div class="stat"><span class="stat-value">{{ snapshot.total_chars }}</span><span class="stat-label">总字符</span></div>
          <div class="stat"><span class="stat-value">{{ snapshot.max_chars }}</span><span class="stat-label">上限</span></div>
          <div class="stat"><span class="stat-value">{{ snapshot.kept_messages }}</span><span class="stat-label">保留消息</span></div>
          <div class="stat"><span class="stat-value">{{ snapshot.dropped_messages }}</span><span class="stat-label">丢弃消息</span></div>
        </div>
        <div class="compress-row">
          <span class="badge" :class="snapshot.compressed ? 'badge-amber' : 'badge-green'">
            {{ snapshot.compressed ? '已压缩历史' : '未压缩' }}
          </span>
        </div>
        <h4 class="block-title">分段明细</h4>
        <div v-if="snapshot.sections.length" class="section-list">
          <div v-for="section in snapshot.sections" :key="section.name" class="section-row">
            <div class="section-main">
              <span class="section-name">{{ section.name }}</span>
              <span class="badge" :class="section.included ? 'badge-green' : 'badge-red'">
                {{ section.included ? '已包含' : '已裁剪' }}
              </span>
              <span v-if="section.truncated" class="badge badge-amber">已截断</span>
            </div>
            <span class="mono small muted">{{ section.chars }} chars</span>
          </div>
        </div>
        <div v-else class="empty-state">暂无上下文分段</div>
      </div>
      <div v-else class="empty-state">发送请求或点击「上下文预览」后展示快照</div>
    </aside>
  </div>
</template>

<style scoped>
.chat-layout { display: flex; gap: 18px; align-items: stretch; }
.chat-main { flex: 1; min-width: 0; display: flex; flex-direction: column; height: calc(100vh - 64px - 56px); min-height: 560px; }
.chat-toolbar {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 12px 18px; border-bottom: 1px solid #eef0f4;
}
.toolbar-left, .toolbar-right { display: flex; align-items: center; gap: 10px; }
.thread-field { display: flex; align-items: center; gap: 6px; }
.thread-input { width: 120px; padding: 5px 8px; font-size: 12px; }

.message-list { flex: 1; overflow-y: auto; padding: 20px 18px; background: #fcfdff; }
.message-row { display: flex; margin-bottom: 18px; }
.message-row.user { justify-content: flex-end; }
.message-row.assistant { justify-content: flex-start; }
.bubble { max-width: 82%; padding: 12px 15px; border-radius: 12px; }
.bubble-user { background: #2563eb; color: #fff; border-bottom-right-radius: 3px; }
.bubble-assistant { background: #fff; border: 1px solid #e6e9ef; border-bottom-left-radius: 3px; }
.bubble-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.speaker { font-size: 12px; font-weight: 600; opacity: 0.85; }
.bubble-content { white-space: pre-wrap; word-break: break-word; line-height: 1.7; font-size: 13.5px; }
.bubble-content.empty { color: #9ca3af; }
.bubble-user .bubble-content { color: #fff; }
.caret { display: inline-block; width: 6px; height: 14px; background: #2563eb; vertical-align: -2px; animation: blink 0.9s steps(2) infinite; }
@keyframes blink { 50% { opacity: 0; } }

.node-trail { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; margin-bottom: 8px; font-size: 11px; color: #64748b; }
.trail-node { background: #f1f5f9; border-radius: 4px; padding: 1px 6px; }
.trail-arrow { color: #a1a9b7; }
.tool-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.chip { display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px; border-radius: 999px; background: #eef2ff; color: #4338ca; font-size: 11px; max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-dot { width: 5px; height: 5px; border-radius: 50%; background: #6366f1; flex: 0 0 5px; }

.error-banner { margin: 0 18px 10px; padding: 8px 12px; border-radius: 8px; background: #fef2f2; color: #b91c1c; font-size: 12px; }
.composer { padding: 12px 18px 16px; border-top: 1px solid #eef0f4; }
.quick-prompts { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-bottom: 10px; }
.prompt-btn { padding: 4px 10px; border: 1px solid #dbe3f0; border-radius: 999px; background: #f7faff; color: #3b5fa8; font-size: 12px; cursor: pointer; }
.prompt-btn:hover { background: #ebf2ff; }
.composer-box { border: 1px solid #d9dee7; border-radius: 10px; overflow: hidden; background: #fff; }
.composer-input { border: none; border-radius: 0; resize: none; box-shadow: none !important; padding: 11px 13px; }
.composer-foot { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; border-top: 1px solid #eef0f4; }

.context-panel { width: 330px; flex: 0 0 330px; display: flex; flex-direction: column; max-height: calc(100vh - 64px - 56px); }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 8px; padding: 14px 16px; border-bottom: 1px solid #eef0f4; }
.panel-body { overflow-y: auto; padding: 14px 16px; }
.stats-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.stat { background: #f7f9fc; border-radius: 8px; padding: 9px 11px; display: flex; flex-direction: column; }
.stat-value { font-size: 17px; font-weight: 650; }
.stat-label { font-size: 11px; color: #9ca3af; }
.compress-row { margin: 12px 0; }
.block-title { font-size: 12px; font-weight: 600; color: #6b7280; margin: 6px 0 8px; }
.section-list { display: flex; flex-direction: column; gap: 6px; }
.section-row { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 8px 9px; border: 1px solid #eef0f4; border-radius: 8px; }
.section-main { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; }
.section-name { font-size: 12px; font-weight: 500; }

@media (max-width: 1100px) {
  .context-panel { width: 280px; flex-basis: 280px; }
}
@media (max-width: 900px) {
  .chat-layout { flex-direction: column; }
  .chat-main, .context-panel { height: auto; max-height: none; min-height: 520px; width: 100%; flex-basis: auto; }
}
</style>
