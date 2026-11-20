<script setup>
import { computed } from 'vue'
import AppIcon from '../AppIcon.vue'
import EmptyState from '../ui/EmptyState.vue'

const props = defineProps({
  citations: { type: Array, default: () => [] },
})

const STATUS = {
  active: { label: '生效中', cls: 'chip--success' },
  archived: { label: '已归档', cls: 'chip--neutral' },
  draft: { label: '讨论稿', cls: 'chip--warning' },
  expired: { label: '已失效', cls: 'chip--danger' },
  superseded: { label: '已被替代', cls: 'chip--danger' },
}

function statusInfo(status) {
  return STATUS[String(status || '').toLowerCase()] || { label: status || '状态未知', cls: 'chip--neutral' }
}

function scorePercent(score) {
  const value = Number(score)
  if (!Number.isFinite(value)) return null
  return Math.round(Math.min(1, Math.max(0, value)) * 100)
}

const activeCount = computed(() => props.citations.filter((item) => item.status === 'active').length)
</script>

<template>
  <div class="citations-tab">
    <div v-if="citations.length" class="citations-summary">
      <span class="citations-summary__count">{{ citations.length }} 条引用证据</span>
      <span class="citations-summary__note">制度类回答必须带文档编号、版本与条款</span>
    </div>

    <EmptyState
      v-if="!citations.length"
      icon="quote"
      title="本次回答没有引用"
      message="查询余额、提交申请等操作不需要制度引用；制度类问题会在这里列出命中的文档、版本与条款片段。"
    />

    <article
      v-for="(citation, index) in citations"
      :key="`${citation.doc_id}-${citation.heading}-${index}`"
      class="citation"
    >
      <header class="citation__head">
        <div class="citation__title-wrap">
          <span class="citation__index">{{ String(index + 1).padStart(2, '0') }}</span>
          <h3 class="citation__title">{{ citation.title || citation.doc_id || '未命名文档' }}</h3>
        </div>
        <span class="chip chip--xs" :class="statusInfo(citation.status).cls">
          {{ statusInfo(citation.status).label }}
        </span>
      </header>

      <p class="citation__heading">
        <AppIcon name="file-text" :size="13" />
        <span v-if="citation.heading">{{ citation.heading }}</span>
        <span v-else>未标注条款位置</span>
      </p>

      <p v-if="citation.snippet" class="citation__snippet">{{ citation.snippet }}</p>

      <footer class="citation__foot">
        <span class="citation__meta">
          <span class="citation__meta-label">doc_id</span>
          <code>{{ citation.doc_id || '—' }}</code>
        </span>
        <span class="citation__meta">
          <span class="citation__meta-label">版本</span>
          <span>{{ citation.version || '—' }}</span>
        </span>
        <span v-if="scorePercent(citation.score) !== null" class="citation__score">
          <span class="citation__score-bar" aria-hidden="true">
            <span :style="{ width: `${scorePercent(citation.score)}%` }"></span>
          </span>
          相关度 {{ scorePercent(citation.score) }}%
        </span>
      </footer>
    </article>

    <p v-if="citations.length" class="citations-foot">
      只有 <b>{{ activeCount }}</b> 条处于生效状态。生产环境需校验「引用是否支撑结论、是否最新版本、是否有权限阅读」。
    </p>
  </div>
</template>

<style scoped>
.citations-tab { padding: 14px; }
.citations-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 10px;
  margin-bottom: 12px;
}
.citations-summary__count { font-size: 12px; font-weight: 650; color: var(--text-2); }
.citations-summary__note { font-size: 10.5px; color: var(--text-4); }
.citation {
  margin-bottom: 11px;
  padding: 12px 13px;
  border: 1px solid var(--border);
  border-radius: 11px;
  background: #fff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.citation:hover { border-color: var(--brand-200); box-shadow: var(--shadow-sm); }
.citation__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}
.citation__title-wrap { display: flex; align-items: baseline; gap: 7px; min-width: 0; }
.citation__index {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-4);
  flex: none;
}
.citation__title {
  margin: 0;
  font-size: 13px;
  line-height: 1.55;
  letter-spacing: -0.01em;
  color: var(--text);
}
.citation__heading {
  display: flex;
  align-items: flex-start;
  gap: 5px;
  margin: 6px 0 0;
  color: var(--brand-700);
  font-size: 11.5px;
  line-height: 1.6;
}
.citation__heading svg { flex: none; margin-top: 1px; }
.citation__snippet {
  margin: 7px 0 0;
  padding: 8px 10px;
  border-left: 2px solid var(--brand-200);
  background: var(--surface-2);
  border-radius: 0 7px 7px 0;
  color: var(--text-2);
  font-size: 11.5px;
  line-height: 1.72;
  overflow-wrap: anywhere;
}
.citation__foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  margin-top: 9px;
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  color: var(--text-3);
  font-size: 10.5px;
}
.citation__meta { display: inline-flex; align-items: center; gap: 4px; }
.citation__meta-label { color: var(--text-4); font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.04em; }
.citation__meta code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-2);
  background: var(--surface-3);
  padding: 1px 5px;
  border-radius: 4px;
}
.citation__score { display: inline-flex; align-items: center; gap: 5px; margin-left: auto; font-size: 10px; }
.citation__score-bar {
  width: 44px;
  height: 3px;
  border-radius: 999px;
  background: var(--surface-3);
  overflow: hidden;
}
.citation__score-bar span {
  display: block;
  height: 100%;
  background: linear-gradient(90deg, #818cf8, #6366f1);
  border-radius: 999px;
}
.citations-foot {
  margin: 4px 2px 0;
  padding-top: 10px;
  border-top: 1px solid var(--border);
  color: var(--text-4);
  font-size: 10.5px;
  line-height: 1.7;
}
.citations-foot b { color: var(--text-2); }
</style>
