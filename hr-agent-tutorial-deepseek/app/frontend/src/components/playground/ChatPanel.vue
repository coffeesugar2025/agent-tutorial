<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import AppIcon from '../AppIcon.vue'
import ErrorState from '../ui/ErrorState.vue'
import ChatMessage from './ChatMessage.vue'

const props = defineProps({
  messages: { type: Array, default: () => [] },
  sending: { type: Boolean, default: false },
  error: { type: String, default: '' },
  scenarios: { type: Array, default: () => [] },
  scenariosLoading: { type: Boolean, default: false },
  scenariosError: { type: String, default: '' },
  suggestions: { type: Array, default: () => [] },
  identity: { type: Object, required: true },
})

const emit = defineEmits(['send', 'retry', 'scenario', 'retry-scenarios', 'open-approval'])

const draft = ref('')
const scrollRef = ref(null)
const inputRef = ref(null)

const canSend = computed(() => draft.value.trim().length > 0 && !props.sending)
const placeholder = computed(
  () => `以 ${props.identity.name} 的身份提问，例如：我还有几天年假？`,
)

function scrollToBottom(smooth = true) {
  nextTick(() => {
    const el = scrollRef.value
    if (!el) return
    if (typeof el.scrollTo === 'function') {
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? 'smooth' : 'auto' })
    } else {
      // 兜底：极老环境或测试 DOM 没有 scrollTo
      el.scrollTop = el.scrollHeight
    }
  })
}

watch(
  () => props.messages.length,
  () => scrollToBottom(),
)
watch(
  () => props.sending,
  (value) => {
    if (value) scrollToBottom()
  },
)

function autosize() {
  const el = inputRef.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 132)}px`
}

function submit() {
  const text = draft.value.trim()
  if (!text || props.sending) return
  draft.value = ''
  nextTick(() => {
    autosize()
    inputRef.value?.focus()
  })
  emit('send', text)
}

function onKeydown(event) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  submit()
}

function useScenario(scenario) {
  if (props.sending) return
  emit('scenario', scenario)
}

function isSensitive(scenario) {
  return ['high', 'medium'].includes(String(scenario.risk || '').toLowerCase())
}
</script>

<template>
  <section class="chat-panel" aria-label="HR Agent 对话">
    <header class="chat-panel__head">
      <div class="chat-who">
        <span class="chat-who__avatar" aria-hidden="true">{{ identity.name.slice(0, 1) }}</span>
        <div class="chat-who__text">
          <b>{{ identity.name }}</b>
          <span>{{ identity.role }} · {{ identity.employeeId }}</span>
        </div>
      </div>
      <span class="chat-mode">
        <span class="chat-mode__dot" aria-hidden="true"></span>
        Mock 模式
      </span>
    </header>

    <div ref="scrollRef" class="chat-panel__scroll" role="log" aria-live="polite" aria-label="对话消息">
      <ChatMessage
        v-for="message in messages"
        :key="message.id"
        :message="message"
        @open-approval="emit('open-approval')"
      />

      <div v-if="sending" class="typing" aria-label="Agent 正在回复">
        <span class="typing__avatar" aria-hidden="true"><AppIcon name="sparkles" :size="14" /></span>
        <span class="typing__bubble">
          <span class="typing__dots" aria-hidden="true"><i></i><i></i><i></i></span>
          <span>正在分析意图并调用工具…</span>
        </span>
      </div>

      <ErrorState
        v-if="error"
        class="chat-error"
        compact
        title="消息发送失败"
        :message="error"
        retry-label="重试这条消息"
        :loading="sending"
        @retry="emit('retry')"
      />

      <div v-if="suggestions.length && !sending" class="suggestions">
        <span class="suggestions__label">你可以接着问</span>
        <button
          v-for="(suggestion, index) in suggestions"
          :key="`${suggestion}-${index}`"
          type="button"
          class="suggestion"
          @click="emit('send', suggestion)"
        >
          <AppIcon name="arrow-up-right" :size="13" />
          <span>{{ suggestion }}</span>
        </button>
      </div>
    </div>

    <div class="quick">
      <div class="quick__head">
        <span class="quick__title">
          <AppIcon name="spark" :size="14" />
          快捷场景
        </span>
        <span class="quick__hint">
          带锁标的场景会触发人工审批
        </span>
      </div>

      <div v-if="scenariosLoading" class="quick__skeleton" aria-hidden="true">
        <span v-for="i in 4" :key="i" class="skeleton"></span>
      </div>
      <div v-else-if="scenariosError" class="quick__error">
        <span>{{ scenariosError }}</span>
        <button type="button" class="quick__retry" @click="emit('retry-scenarios')">
          <AppIcon name="refresh" :size="12" /> 重试
        </button>
      </div>
      <div v-else-if="scenarios.length" class="quick__chips">
        <button
          v-for="scenario in scenarios"
          :key="scenario.id || scenario.label"
          type="button"
          class="quick-chip"
          :disabled="sending"
          :title="scenario.message"
          @click="useScenario(scenario)"
        >
          <AppIcon v-if="isSensitive(scenario)" name="lock" :size="12" />
          <span>{{ scenario.label }}</span>
        </button>
      </div>
      <p v-else class="quick__empty">场景接口暂无数据，直接输入问题也可以。</p>
    </div>

    <form class="composer" @submit.prevent="submit">
      <label class="sr-only" :for="`chat-input-${identity.employeeId}`">输入问题</label>
      <textarea
        :id="`chat-input-${identity.employeeId}`"
        ref="inputRef"
        v-model="draft"
        class="textarea composer__input"
        rows="2"
        :placeholder="placeholder"
        :disabled="sending"
        @input="autosize"
        @keydown="onKeydown"
      ></textarea>
      <div class="composer__bar">
        <span class="composer__hint">Enter 发送 · Shift + Enter 换行</span>
        <button type="submit" class="btn btn--primary btn--sm" :disabled="!canSend">
          <span v-if="sending" class="spinner"></span>
          <AppIcon v-else name="send" :size="15" />
          {{ sending ? '思考中…' : '发送' }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.chat-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.chat-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  flex: none;
}
.chat-who { display: flex; align-items: center; gap: 9px; min-width: 0; }
.chat-who__avatar {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  color: var(--brand-700);
  font-size: 13px;
  font-weight: 700;
  flex: none;
}
.chat-who__text { display: flex; flex-direction: column; line-height: 1.4; min-width: 0; }
.chat-who__text b { font-size: 13px; color: var(--text); }
.chat-who__text span { font-size: 10.5px; color: var(--text-3); }
.chat-mode {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: #fff;
  color: var(--text-3);
  font-size: 10.5px;
  white-space: nowrap;
}
.chat-mode__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #12b76a;
  box-shadow: 0 0 0 2px rgba(18, 183, 106, 0.14);
}

.chat-panel__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  scroll-behavior: smooth;
  background:
    radial-gradient(420px 220px at 100% 0%, rgba(238, 242, 255, 0.55), transparent 70%),
    #fff;
}
.chat-error { flex: none; }

.typing { display: flex; gap: 9px; align-items: flex-start; }
.typing__avatar {
  display: grid;
  place-items: center;
  width: 27px;
  height: 27px;
  border-radius: 8px;
  color: var(--brand-700);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
  flex: none;
}
.typing__bubble {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 4px 12px 12px 12px;
  background: #fff;
  color: var(--text-3);
  font-size: 12px;
}
.typing__dots { display: inline-flex; gap: 3px; }
.typing__dots i {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--brand-200);
  animation: typing-bounce 1.2s ease-in-out infinite;
}
.typing__dots i:nth-child(2) { animation-delay: 0.15s; }
.typing__dots i:nth-child(3) { animation-delay: 0.3s; }
@keyframes typing-bounce {
  0%, 60%, 100% { transform: translateY(0); opacity: 0.6; }
  30% { transform: translateY(-3px); opacity: 1; }
}

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 2px;
}
.suggestions__label {
  width: 100%;
  font-size: 10.5px;
  color: var(--text-4);
}
.suggestion {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  padding: 5px 10px;
  border: 1px solid var(--brand-100);
  border-radius: 999px;
  background: #fff;
  color: var(--brand-700);
  font-size: 11.5px;
  line-height: 1.5;
  text-align: left;
  transition: background-color 0.15s ease, border-color 0.15s ease;
}
.suggestion:hover { background: var(--brand-50); border-color: var(--brand-200); }
.suggestion span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.quick {
  flex: none;
  padding: 10px 14px;
  border-top: 1px solid var(--border);
  background: var(--surface-2);
}
.quick__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 7px;
}
.quick__title {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-weight: 650;
  color: var(--text-2);
}
.quick__title svg { color: var(--brand); }
.quick__hint { font-size: 10px; color: var(--text-4); }
.quick__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 92px;
  overflow-y: auto;
}
.quick-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 9px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: #fff;
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.55;
  transition: border-color 0.15s ease, background-color 0.15s ease, color 0.15s ease;
}
.quick-chip:hover:not(:disabled) { border-color: var(--brand-200); background: var(--brand-50); color: var(--brand-700); }
.quick-chip:disabled { opacity: 0.55; cursor: not-allowed; }
.quick-chip svg { color: var(--warning); flex: none; }
.quick__skeleton { display: flex; flex-wrap: wrap; gap: 6px; }
.quick__skeleton .skeleton { width: 118px; height: 24px; border-radius: 999px; }
.quick__skeleton .skeleton:nth-child(2) { width: 148px; }
.quick__skeleton .skeleton:nth-child(3) { width: 132px; }
.quick__skeleton .skeleton:nth-child(4) { width: 96px; }
.quick__error {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 11.5px;
  color: var(--danger);
}
.quick__retry {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px;
  border: 1px solid var(--danger-border);
  border-radius: 6px;
  background: #fff;
  color: var(--danger);
  font-size: 11px;
}
.quick__empty { margin: 0; font-size: 11.5px; color: var(--text-4); }

.composer {
  flex: none;
  padding: 10px 14px 12px;
  border-top: 1px solid var(--border);
  background: #fff;
}
.composer__input {
  min-height: 54px;
  max-height: 132px;
  resize: none;
  font-size: 13.5px;
  line-height: 1.65;
  padding: 9px 11px;
}
.composer__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 7px;
}
.composer__hint { font-size: 10.5px; color: var(--text-4); }
</style>
