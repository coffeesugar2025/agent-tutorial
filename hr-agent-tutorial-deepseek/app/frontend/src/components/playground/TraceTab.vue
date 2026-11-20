<script setup>
import { computed } from 'vue'
import AppIcon from '../AppIcon.vue'
import EmptyState from '../ui/EmptyState.vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  status: { type: String, default: '' },
  usage: { type: Object, default: null },
})

const TYPE_LABELS = {
  llm: { label: '模型', icon: 'sparkles' },
  tool: { label: '工具', icon: 'tool' },
  retrieval: { label: '检索', icon: 'search' },
  approval: { label: '审批', icon: 'shield' },
  final: { label: '汇总', icon: 'check' },
}

const totalDuration = computed(() =>
  props.steps.reduce((sum, step) => sum + (Number(step.duration_ms) || 0), 0),
)

const errorCount = computed(() => props.steps.filter((step) => step.status === 'error').length)

function typeInfo(type) {
  return TYPE_LABELS[type] || { label: type || '步骤', icon: 'activity' }
}

function statusIcon(status) {
  if (status === 'error') return 'alert-circle'
  if (status === 'pending') return 'clock'
  return 'check-circle'
}

function hasData(step) {
  return step.data && typeof step.data === 'object' && Object.keys(step.data).length > 0
}
</script>

<template>
  <div class="trace-tab">
    <div v-if="steps.length" class="trace-summary">
      <span class="trace-summary__item">
        <AppIcon name="layers" :size="14" />
        {{ steps.length }} 个步骤
      </span>
      <span class="trace-summary__item">
        <AppIcon name="timer" :size="14" />
        总耗时 {{ totalDuration }} ms
      </span>
      <span v-if="errorCount" class="trace-summary__item trace-summary__item--error">
        <AppIcon name="alert-circle" :size="14" />
        {{ errorCount }} 步失败
      </span>
      <span v-else-if="status === 'pending_approval'" class="chip chip--warning chip--xs">已暂停，等待审批</span>
      <span v-else-if="status === 'completed'" class="chip chip--success chip--xs">已正常结束</span>
    </div>

    <EmptyState
      v-if="!steps.length"
      icon="activity"
      title="还没有执行轨迹"
      message="发送一条消息后，这里会按顺序展示意图识别、工具调用、检索与生成回答的每一步。"
    />

    <ol v-else class="timeline">
      <li
        v-for="(step, index) in steps"
        :key="step.index ?? index"
        class="step"
        :class="[`step--${step.status || 'ok'}`]"
      >
        <span class="step__rail" aria-hidden="true">
          <span class="step__dot"><AppIcon :name="statusIcon(step.status)" :size="13" /></span>
        </span>
        <div class="step__card">
          <div class="step__head">
            <span class="step__index">#{{ step.index ?? index + 1 }}</span>
            <span class="step__title">{{ step.title || '未命名步骤' }}</span>
            <span class="step__type">
              <AppIcon :name="typeInfo(step.type).icon" :size="11" />
              {{ typeInfo(step.type).label }}
            </span>
            <span class="step__duration">{{ step.duration_ms ?? 0 }} ms</span>
          </div>
          <p v-if="step.detail" class="step__detail">{{ step.detail }}</p>

          <details v-if="hasData(step)" class="step__data">
            <summary>查看返回数据</summary>
            <pre>{{ JSON.stringify(step.data, null, 2) }}</pre>
          </details>
        </div>
      </li>
    </ol>

    <p v-if="steps.length" class="trace-foot">
      Trace 字段与后端 <code>/api/chat</code> 的 <code>steps</code> 一一对应；生产环境可上报到 OpenTelemetry。
    </p>
  </div>
</template>

<style scoped>
.trace-tab { padding: 14px; }
.trace-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 14px;
  padding: 9px 12px;
  margin-bottom: 14px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface-2);
}
.trace-summary__item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--text-3);
  font-size: 11.5px;
}
.trace-summary__item svg { color: var(--text-4); }
.trace-summary__item--error { color: var(--danger); }
.trace-summary__item--error svg { color: var(--danger); }
.timeline { list-style: none; margin: 0; padding: 0; }
.step { display: flex; gap: 10px; }
.step__rail {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: none;
  width: 24px;
}
.step__dot {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--success-soft);
  color: var(--success);
  border: 1px solid var(--success-border);
  z-index: 1;
}
.step--error .step__dot { background: var(--danger-soft); color: var(--danger); border-color: var(--danger-border); }
.step--pending .step__dot { background: var(--warning-soft); color: var(--warning); border-color: var(--warning-border); }
.step:not(:last-child) .step__rail::after {
  content: "";
  position: absolute;
  top: 24px;
  bottom: -2px;
  width: 2px;
  background: var(--border);
}
.step__card {
  flex: 1;
  min-width: 0;
  padding: 8px 11px 10px;
  margin-bottom: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: #fff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.step__card:hover { border-color: var(--brand-200); box-shadow: var(--shadow-sm); }
.step--error .step__card { border-color: var(--danger-border); background: #fffafa; }
.step__head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.step__index {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-4);
}
.step__title { font-size: 12.5px; font-weight: 650; color: var(--text); }
.step__type {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1.7;
}
.step--error .step__type { background: var(--danger-soft); color: var(--danger); }
.step__duration {
  margin-left: auto;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-4);
}
.step__detail {
  margin: 5px 0 0;
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-3);
  overflow-wrap: anywhere;
}
.step__data { margin-top: 6px; }
.step__data summary {
  font-size: 10.5px;
  color: var(--text-4);
  cursor: pointer;
  user-select: none;
  width: fit-content;
  padding: 1px 0;
}
.step__data summary:hover { color: var(--brand-700); }
.step__data pre {
  margin: 6px 0 0;
  padding: 8px 10px;
  border-radius: 7px;
  background: #f6f7fb;
  border: 1px solid var(--border);
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.6;
  color: var(--text-2);
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.trace-foot {
  margin: 8px 2px 0;
  color: var(--text-4);
  font-size: 10.5px;
  line-height: 1.7;
}
.trace-foot code {
  font-family: var(--font-mono);
  font-size: 10px;
  padding: 0 3px;
  border-radius: 3px;
  background: var(--surface-3);
}
</style>
