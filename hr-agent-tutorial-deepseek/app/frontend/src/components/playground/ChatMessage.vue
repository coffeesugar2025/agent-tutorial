<script setup>
import { computed, onBeforeUnmount } from 'vue'
import { copyText } from '../../lib/clipboard.js'
import { renderMarkdown } from '../../lib/markdown.js'
import AppIcon from '../AppIcon.vue'
import RiskBadge from '../ui/RiskBadge.vue'

const props = defineProps({
  message: { type: Object, required: true },
})

const emit = defineEmits(['open-approval'])

const isUser = computed(() => props.message.role === 'user')
const isSystem = computed(() => props.message.role === 'system')

const html = computed(() => {
  if (isUser.value || isSystem.value) return ''
  // 聊天内容统一先转义原始 HTML 再渲染 Markdown，避免 XSS。
  return renderMarkdown(props.message.content || '', {
    escapeRawHtml: true,
    callouts: false,
    codeCopy: true,
  }).html
})

const meta = computed(() => props.message.meta || {})
const statusInfo = computed(() => {
  const map = {
    completed: { label: '已完成', cls: 'badge--success' },
    pending_approval: { label: '待审批', cls: 'badge--pending' },
    escalated: { label: '已转人工', cls: 'badge--neutral' },
    error: { label: '出错', cls: 'badge--danger' },
    approved: { label: '审批通过', cls: 'badge--success' },
    rejected: { label: '审批拒绝', cls: 'badge--danger' },
    failed: { label: '执行失败', cls: 'badge--danger' },
  }
  return map[meta.value.status] || null
})

const approval = computed(() => meta.value.approval || null)

let copyTimer = null

async function onClick(event) {
  const button = event.target.closest?.('.code-copy')
  if (!button) return
  const code = button.closest('.code-block')?.querySelector('pre code')
  if (!code) return
  await copyText(code.textContent)
  const label = button.querySelector('span')
  button.classList.add('is-copied')
  if (label) label.textContent = '已复制'
  clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    button.classList.remove('is-copied')
    if (label) label.textContent = '复制'
  }, 1600)
}

onBeforeUnmount(() => clearTimeout(copyTimer))
</script>

<template>
  <div class="msg" :class="[`msg--${message.role}`, { 'msg--result': meta.approvalResult }]" @click="onClick">
    <span v-if="!isUser && !isSystem" class="msg__avatar" aria-hidden="true">
      <AppIcon name="sparkles" :size="14" />
    </span>

    <div class="msg__body">
      <template v-if="isUser">
        <p class="msg__user-text">{{ message.content }}</p>
      </template>

      <template v-else-if="isSystem">
        <p class="msg__system-text">
          <AppIcon name="info" :size="13" />
          <span>{{ message.content }}</span>
        </p>
      </template>

      <template v-else>
        <div class="msg__md md-body" v-html="html"></div>

        <div v-if="statusInfo || meta.intent || meta.totalMs != null || meta.usage" class="msg__meta">
          <span v-if="statusInfo" class="badge" :class="statusInfo.cls">{{ statusInfo.label }}</span>
          <span v-if="meta.intent" class="msg__meta-item">
            <AppIcon name="activity" :size="12" />
            <code>{{ meta.intent }}</code>
          </span>
          <span v-if="meta.stepsCount" class="msg__meta-item">
            <AppIcon name="layers" :size="12" />
            {{ meta.stepsCount }} 步
          </span>
          <span v-if="meta.citationsCount" class="msg__meta-item">
            <AppIcon name="quote" :size="12" />
            引用 {{ meta.citationsCount }}
          </span>
          <span v-if="meta.usage?.total_tokens" class="msg__meta-item">
            <AppIcon name="chip" :size="12" />
            {{ meta.usage.total_tokens }} tokens
          </span>
          <span v-if="meta.totalMs != null" class="msg__meta-item">
            <AppIcon name="clock" :size="12" />
            {{ meta.totalMs }} ms
          </span>
        </div>

        <div v-if="approval" class="msg__approval">
          <div class="msg__approval-head">
            <RiskBadge :risk="approval.risk" size="sm" />
            <span>已生成审批单 <code>{{ approval.id }}</code></span>
          </div>
          <p class="msg__approval-summary">{{ approval.summary }}</p>
          <button type="button" class="btn btn--secondary btn--sm" @click="emit('open-approval')">
            <AppIcon name="shield" :size="14" />
            去审批
            <AppIcon name="arrow-right" :size="13" />
          </button>
        </div>

        <div v-if="meta.approvalResult" class="msg__result">
          <AppIcon :name="meta.status === 'approved' ? 'check-circle' : 'alert-circle'" :size="15" />
          <span>
            审批单 <code>{{ meta.approvalId }}</code>
            {{ meta.status === 'approved' ? '已通过并执行' : meta.status === 'rejected' ? '已拒绝，未执行' : '执行失败' }}
            <template v-if="meta.auditId"> · 审计 <code>{{ meta.auditId }}</code></template>
          </span>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.msg {
  display: flex;
  gap: 9px;
  align-items: flex-start;
  max-width: 100%;
}
.msg--user { justify-content: flex-end; }
.msg--system { justify-content: center; }
.msg__avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 27px;
  height: 27px;
  margin-top: 2px;
  border-radius: 8px;
  color: var(--brand-700);
  background: var(--brand-50);
  border: 1px solid var(--brand-100);
}
.msg__body { min-width: 0; max-width: 92%; }
.msg--user .msg__body { max-width: 86%; display: flex; justify-content: flex-end; }
.msg--system .msg__body { max-width: 100%; }
.msg__user-text {
  margin: 0;
  padding: 9px 13px;
  border-radius: 13px 13px 4px 13px;
  background: var(--brand);
  color: #fff;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  box-shadow: 0 8px 18px -14px rgba(79, 70, 229, 0.9);
}
.msg__system-text {
  display: inline-flex;
  align-items: flex-start;
  gap: 5px;
  margin: 0;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--surface-3);
  color: var(--text-3);
  font-size: 11.5px;
  line-height: 1.6;
}
.msg__system-text svg { flex: none; margin-top: 1px; }
.msg--assistant .msg__body {
  padding: 11px 14px;
  border: 1px solid var(--border);
  border-radius: 4px 13px 13px 13px;
  background: #fff;
  box-shadow: var(--shadow-sm);
}
.msg__md { font-size: 14.3px; line-height: 1.78; }
.msg__md :deep(p) { margin: 0 0 8px; }
.msg__md :deep(p:last-child) { margin-bottom: 0; }
.msg__md :deep(ul),
.msg__md :deep(ol) { margin: 4px 0 8px; padding-left: 1.35em; }
.msg__md :deep(li) { margin: 2px 0; }
.msg__md :deep(h1),
.msg__md :deep(h2),
.msg__md :deep(h3),
.msg__md :deep(h4) { margin: 10px 0 6px; padding: 0; border: 0; font-size: 15px; }
.msg__md :deep(.code-block) { margin: 10px 0; border-radius: 10px; }
.msg__md :deep(.code-block pre) { padding: 10px 12px; font-size: 12px; }
.msg__md :deep(.table-wrap) { margin: 10px 0; }
.msg__md :deep(blockquote) { margin: 8px 0; padding: 6px 12px; font-size: 13.5px; }
.msg__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 10px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  color: var(--text-4);
  font-size: 10.5px;
}
.msg__meta-item { display: inline-flex; align-items: center; gap: 3px; }
.msg__meta-item code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-2);
  background: var(--surface-3);
  padding: 0 4px;
  border-radius: 4px;
}
.msg__approval {
  margin-top: 10px;
  padding: 10px 12px;
  border: 1px solid var(--warning-border);
  border-radius: 10px;
  background: var(--warning-soft);
}
.msg__approval-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11.5px;
  color: var(--warning);
  font-weight: 600;
}
.msg__approval-head code { font-family: var(--font-mono); font-size: 10.5px; }
.msg__approval-summary { margin: 6px 0 8px; font-size: 12.5px; line-height: 1.65; color: var(--text-2); }
.msg__result {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.6;
}
.msg__result svg { flex: none; margin-top: 1px; color: var(--success); }
.msg__result code { font-family: var(--font-mono); font-size: 10.5px; color: var(--text); }
.msg--result .msg__md { font-size: 13.8px; }
</style>
