<template>
  <div class="approval-card" :class="{ 'is-resolved': resolved }">
    <div class="approval-card__head">
      <span class="approval-card__icon">⚠</span>
      <div class="approval-card__title-wrap">
        <div class="approval-card__title">{{ approval.title }}</div>
        <div class="approval-card__subtitle">高风险操作需要人工确认 · 审批 #{{ approval.approvalId }}</div>
      </div>
      <el-tag size="small" :type="riskMeta.tone" effect="dark">{{ riskMeta.label }}</el-tag>
      <el-tag size="small" :type="statusMeta.tone" effect="plain">{{ statusMeta.label }}</el-tag>
    </div>

    <div class="approval-card__body">
      <div class="approval-card__label">操作详情</div>
      <pre class="approval-card__json">{{ detailText }}</pre>
    </div>

    <div class="approval-card__timer" :class="{ 'is-danger': isUrgent, 'is-expired': expired }">
      <template v-if="expired">已过期，请让助手重新发起</template>
      <template v-else-if="hasExpiry">剩余 <strong>{{ countdown }}</strong> 后自动失效</template>
      <template v-else>有效期未知</template>
    </div>

    <div v-if="!resolved" class="approval-card__form">
      <el-input
        v-model="comment"
        type="textarea"
        :rows="2"
        maxlength="200"
        show-word-limit
        placeholder="备注（可选，会记录到审计日志）"
        :disabled="busy || expired"
      />
      <div class="approval-card__actions">
        <el-button
          type="success"
          size="small"
          :loading="busy && pendingDecision === 'APPROVE'"
          :disabled="busy || expired"
          @click="submit('APPROVE')"
        >
          同意
        </el-button>
        <el-button
          type="danger"
          size="small"
          plain
          :loading="busy && pendingDecision === 'REJECT'"
          :disabled="busy || expired"
          @click="submit('REJECT')"
        >
          拒绝
        </el-button>
      </div>
    </div>

    <div v-else class="approval-card__result">
      <div class="approval-card__label">执行结果</div>
      <pre v-if="hasResult" class="approval-card__json">{{ resultText }}</pre>
      <p v-else class="approval-card__muted">审批已提交，后端未返回执行结果。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import dayjs from 'dayjs'
import type { ApprovalDecision, ApprovalDecisionPayload, ChatApproval } from '@/types'
import { RISK_META, APPROVAL_STATUS_META, formatJson, metaOf } from '@/utils/format'

const props = withDefaults(
  defineProps<{
    approval: ChatApproval
    busy?: boolean
  }>(),
  { busy: false },
)

const emit = defineEmits<{ decide: [payload: ApprovalDecisionPayload] }>()

const comment = ref('')
const now = ref(Date.now())
const pendingDecision = ref<ApprovalDecision | null>(null)
let timer: number | null = null

const riskMeta = computed(() => metaOf(RISK_META, props.approval.risk))
const statusMeta = computed(() => metaOf(APPROVAL_STATUS_META, props.approval.status))
const resolved = computed(() => props.approval.status !== 'PENDING')

const expiresAtMs = computed(() => {
  const parsed = dayjs(props.approval.expiresAt)
  return parsed.isValid() ? parsed.valueOf() : 0
})
const hasExpiry = computed(() => expiresAtMs.value > 0)
const remainingMs = computed(() => (hasExpiry.value ? Math.max(0, expiresAtMs.value - now.value) : 0))
const expired = computed(() => !resolved.value && hasExpiry.value && remainingMs.value <= 0)
const isUrgent = computed(() => hasExpiry.value && remainingMs.value > 0 && remainingMs.value < 60_000)

const countdown = computed(() => {
  if (!hasExpiry.value) return '—'
  const total = Math.ceil(remainingMs.value / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
})

const detailText = computed(() => formatJson(props.approval.detail ?? {}))
const hasResult = computed(() => Boolean(props.approval.result && Object.keys(props.approval.result).length > 0))
const resultText = computed(() => formatJson(props.approval.result ?? {}))

function stopTimer(): void {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function submit(decision: ApprovalDecision): void {
  if (props.busy || resolved.value || expired.value) return
  pendingDecision.value = decision
  emit('decide', {
    approvalId: props.approval.approvalId,
    decision,
    comment: comment.value.trim(),
  })
}

onMounted(() => {
  timer = window.setInterval(() => {
    now.value = Date.now()
    if (resolved.value) stopTimer()
  }, 1000)
})

onBeforeUnmount(stopTimer)
</script>

<style scoped lang="scss">
.approval-card {
  margin-top: 10px;
  padding: 12px;
  background: #fff7ed;
  border: 1px solid #fed7aa;
  border-left: 3px solid var(--ecom-warning);
  border-radius: 8px;

  &.is-resolved {
    background: #f8fafc;
    border-color: var(--ecom-border);
    border-left-color: var(--ecom-info);
  }

  &__head {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }

  &__icon {
    font-size: 15px;
    line-height: 22px;
    color: var(--ecom-warning);
  }

  &__title-wrap {
    flex: 1;
    min-width: 0;
  }

  &__title {
    font-size: 13px;
    font-weight: 600;
    color: var(--ecom-text-primary);
  }

  &__subtitle {
    margin-top: 2px;
    font-size: 11px;
    color: var(--ecom-text-secondary);
  }

  &__label {
    margin: 10px 0 4px;
    font-size: 11px;
    font-weight: 600;
    color: var(--ecom-text-secondary);
  }

  &__json {
    max-height: 180px;
    margin: 0;
    padding: 8px 10px;
    overflow: auto;
    font-family: var(--ecom-font-mono, monospace);
    font-size: 11.5px;
    line-height: 1.55;
    color: #334155;
    white-space: pre-wrap;
    word-break: break-word;
    background: #fff;
    border: 1px solid var(--ecom-border);
    border-radius: 6px;
  }

  &__timer {
    margin-top: 8px;
    font-size: 12px;
    color: var(--ecom-warning);

    strong {
      font-variant-numeric: tabular-nums;
    }

    &.is-danger {
      color: var(--ecom-danger);
    }

    &.is-expired {
      color: var(--ecom-text-secondary);
    }
  }

  &__form {
    margin-top: 8px;
  }

  &__actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 8px;
  }

  &__muted {
    margin: 0;
    font-size: 12px;
    color: var(--ecom-text-secondary);
  }
}
</style>
