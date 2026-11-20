<script setup>
import { computed, ref, watch } from 'vue'
import AppIcon from '../AppIcon.vue'
import EmptyState from '../ui/EmptyState.vue'
import RiskBadge from '../ui/RiskBadge.vue'

const props = defineProps({
  approval: { type: Object, default: null },
  submitting: { type: Boolean, default: false },
  error: { type: String, default: '' },
  approverName: { type: String, default: '' },
  approverId: { type: String, default: '' },
})

const emit = defineEmits(['decide'])

const comment = ref('')

const ACTION_LABELS = {
  adjust_salary: '调整薪资带宽',
  schedule_interview: '安排面试日程',
  submit_leave_request: '提交请假申请',
  start_onboarding: '启动入职流程',
}

const status = computed(() => String(props.approval?.status || 'pending').toLowerCase())
const isPending = computed(() => status.value === 'pending')
const actionLabel = computed(
  () => ACTION_LABELS[props.approval?.action] || props.approval?.action || '敏感操作',
)

const statusView = computed(() => {
  const map = {
    approved: { label: '已通过', icon: 'check-circle', cls: 'result--success' },
    rejected: { label: '已拒绝', icon: 'close', cls: 'result--danger' },
    failed: { label: '执行失败', icon: 'alert-circle', cls: 'result--danger' },
    pending: { label: '等待审批', icon: 'clock', cls: 'result--pending' },
    expired: { label: '已过期', icon: 'clock', cls: 'result--danger' },
  }
  return map[status.value] || { label: status.value, icon: 'info', cls: 'result--pending' }
})

const payloadText = computed(() => {
  const payload = props.approval?.payload
  if (!payload) return ''
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload)
  }
})

const requestedAt = computed(() => {
  const value = props.approval?.created_at
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
})

const risk = computed(() => String(props.approval?.risk || 'low').toLowerCase())

watch(
  () => props.approval?.id,
  () => {
    comment.value = ''
  },
)

function decide(decision) {
  if (!isPending.value || props.submitting) return
  emit('decide', { decision, comment: comment.value.trim() })
}
</script>

<template>
  <div class="approval-tab">
    <EmptyState
      v-if="!approval"
      icon="shield"
      title="暂无待审批事项"
      message="涉及调薪、面试安排等敏感操作时，Agent 不会直接执行，而是先在这里生成审批单，等待人工确认。"
    />

    <article v-else class="approval" :class="`approval--${status}`">
      <header class="approval__head">
        <div class="approval__title-wrap">
          <span class="approval__eyebrow">
            审批单 <code>{{ approval.id }}</code>
          </span>
          <h3 class="approval__title">{{ actionLabel }}</h3>
        </div>
        <RiskBadge :risk="approval.risk" />
      </header>

      <p class="approval__summary">{{ approval.summary || '（审批单未提供摘要）' }}</p>

      <dl class="approval__meta">
        <div>
          <dt>发起人</dt>
          <dd><code>{{ approval.requested_by || '—' }}</code></dd>
        </div>
        <div>
          <dt>创建时间</dt>
          <dd>{{ requestedAt }}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd><span class="badge" :class="isPending ? 'badge--pending' : statusView.cls === 'result--success' ? 'badge--success' : 'badge--danger'">{{ statusView.label }}</span></dd>
        </div>
      </dl>

      <div v-if="payloadText" class="approval__payload">
        <span class="approval__payload-label">payload 请求参数</span>
        <pre>{{ payloadText }}</pre>
      </div>

      <div v-if="risk === 'high'" class="approval__risk-note" role="note">
        <AppIcon name="shield-alert" :size="15" />
        <span>高风险操作：通过后会立即执行并写入审计日志。请先核对对象、影响范围与制度依据。</span>
      </div>
      <div v-else-if="risk === 'medium'" class="approval__risk-note approval__risk-note--medium" role="note">
        <AppIcon name="shield" :size="15" />
        <span>中风险操作：通过后会创建外部日程或通知，请确认时间与参与人。</span>
      </div>

      <template v-if="isPending">
        <label class="field-label" for="approval-comment">审批备注（可选）</label>
        <textarea
          id="approval-comment"
          v-model="comment"
          class="textarea approval__comment"
          rows="2"
          placeholder="例如：已核对编制与带宽，同意本次调整"
          :disabled="submitting"
        ></textarea>

        <p v-if="error" class="approval__error" role="alert">
          <AppIcon name="alert-circle" :size="14" />
          {{ error }}
        </p>

        <div class="approval__actions">
          <button
            type="button"
            class="btn btn--secondary approval__reject"
            :disabled="submitting"
            @click="decide('reject')"
          >
            <AppIcon name="close" :size="15" />
            拒绝
          </button>
          <button
            type="button"
            class="btn btn--success"
            :disabled="submitting"
            @click="decide('approve')"
          >
            <span v-if="submitting" class="spinner spinner--light"></span>
            <AppIcon v-else name="check" :size="15" />
            {{ submitting ? '正在提交…' : '通过并执行' }}
          </button>
        </div>

        <p class="approval__note">
          审批将以当前身份
          <b>{{ approverName || '演示用户' }}</b>
          <code v-if="approverId">{{ approverId }}</code>
          记录，并追加到审计日志。生产环境需替换为真实审批流与职责分离。
        </p>
      </template>

      <div v-else class="approval__result" :class="statusView.cls">
        <div class="approval__result-head">
          <AppIcon :name="statusView.icon" :size="17" />
          <b>{{ statusView.label }}</b>
        </div>
        <p>{{ approval.result || (status === 'rejected' ? '审批被拒绝，操作未执行。' : '操作已处理。') }}</p>
        <span v-if="approval.audit_id" class="approval__audit">
          审计记录 <code>{{ approval.audit_id }}</code>
        </span>
      </div>
    </article>
  </div>
</template>

<style scoped>
.approval-tab { padding: 14px; }
.approval {
  padding: 14px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: #fff;
}
.approval--pending { border-color: var(--warning-border); }
.approval__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.approval__title-wrap { min-width: 0; }
.approval__eyebrow {
  font-size: 10.5px;
  color: var(--text-4);
}
.approval__eyebrow code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-2);
  background: var(--surface-3);
  padding: 1px 5px;
  border-radius: 4px;
}
.approval__title {
  margin: 3px 0 0;
  font-size: 16px;
  letter-spacing: -0.01em;
}
.approval__summary {
  margin: 10px 0 0;
  padding: 9px 11px;
  border-radius: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.7;
}
.approval__meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin: 12px 0 0;
  padding: 10px;
  border: 1px dashed var(--border);
  border-radius: 8px;
}
.approval__meta dt { font-size: 9.5px; color: var(--text-4); }
.approval__meta dd { margin: 2px 0 0; font-size: 10.5px; color: var(--text-2); overflow-wrap: anywhere; }
.approval__meta code { font-family: var(--font-mono); font-size: 10px; }
.approval__payload { margin-top: 12px; }
.approval__payload-label {
  display: block;
  margin-bottom: 4px;
  font-size: 10px;
  color: var(--text-4);
}
.approval__payload pre {
  margin: 0;
  padding: 9px 10px;
  border-radius: 8px;
  background: #f6f7fb;
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.65;
  color: var(--text-2);
  overflow-x: auto;
  max-height: 160px;
}
.approval__risk-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--danger-border);
  background: var(--danger-soft);
  color: #912018;
  font-size: 10.5px;
  line-height: 1.65;
}
.approval__risk-note svg { flex: none; margin-top: 1px; }
.approval__risk-note--medium { border-color: var(--warning-border); background: var(--warning-soft); color: #93370d; }
.approval__comment { margin-top: 6px; min-height: 60px; font-size: 12px; }
.approval__error {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin: 8px 0 0;
  padding: 7px 9px;
  border-radius: 7px;
  border: 1px solid var(--danger-border);
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 10.5px;
  line-height: 1.6;
}
.approval__error svg { flex: none; margin-top: 1px; }
.approval__actions {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  gap: 8px;
  margin-top: 12px;
}
.approval__reject { color: var(--danger); border-color: var(--danger-border); }
.approval__reject:hover:not(:disabled) { background: var(--danger-soft); border-color: #fda29b; color: #912018; }
.spinner--light { border-color: rgba(255, 255, 255, 0.35); border-top-color: #fff; }
.approval__note {
  margin: 10px 0 0;
  color: var(--text-4);
  font-size: 9.5px;
  line-height: 1.7;
}
.approval__note b { color: var(--text-2); }
.approval__note code { font-family: var(--font-mono); font-size: 9px; margin-left: 3px; }
.approval__result {
  margin-top: 12px;
  padding: 11px 12px;
  border-radius: 9px;
  border: 1px solid var(--border);
  background: var(--surface-2);
}
.approval__result--success { border-color: var(--success-border); background: var(--success-soft); }
.approval__result--danger { border-color: var(--danger-border); background: var(--danger-soft); }
.approval__result-head {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--success);
}
.result--danger .approval__result-head { color: var(--danger); }
.approval__result p { margin: 5px 0 0; font-size: 11.5px; line-height: 1.7; color: var(--text-2); }
.approval__audit { display: inline-block; margin-top: 6px; font-size: 10px; color: var(--text-3); }
.approval__audit code { font-family: var(--font-mono); font-size: 9.5px; background: #fff; border: 1px solid var(--border); padding: 1px 5px; border-radius: 4px; }
</style>
