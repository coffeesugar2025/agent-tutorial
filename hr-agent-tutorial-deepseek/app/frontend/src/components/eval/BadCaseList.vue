<script setup>
import AppIcon from '../AppIcon.vue'

defineProps({
  cases: { type: Array, default: () => [] },
})
</script>

<template>
  <div class="bad-cases">
    <div class="bad-cases__head">
      <h2 id="badcase-title" class="bad-cases__title">
        <AppIcon name="alert-circle" :size="17" />
        Bad Case 复盘
        <span class="bad-cases__count">{{ cases.length }}</span>
      </h2>
      <p class="bad-cases__hint">评测必须包含失败案例，否则无法定位召回、工具与幻觉问题。</p>
    </div>

    <div v-if="cases.length" class="bad-cases__grid">
      <article v-for="item in cases" :key="item.id" class="bad-case">
        <header class="bad-case__head">
          <span class="bad-case__id">{{ item.id }}</span>
          <span class="bad-case__label">失败</span>
          <span class="bad-case__latency">{{ item.latency_ms ?? '—' }} ms</span>
        </header>
        <p class="bad-case__input">{{ item.input }}</p>
        <ul v-if="item.failures?.length" class="bad-case__failures">
          <li v-for="(failure, index) in item.failures" :key="index">{{ failure }}</li>
        </ul>
        <p v-else class="bad-case__failures-empty">未返回失败原因，需要人工复核。</p>
        <details class="bad-case__reply">
          <summary>查看 Agent 回复</summary>
          <pre>{{ item.reply || '（无回复）' }}</pre>
        </details>
      </article>
    </div>

    <div v-else class="bad-cases__empty">
      <AppIcon name="check-circle" :size="18" />
      <div>
        <b>本次运行没有失败用例</b>
        <p>但建议保留 1–3 条真实失败样本用于教学与回归，避免“只报喜”的评测。</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bad-cases { margin-top: 34px; }
.bad-cases__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.bad-cases__title {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 0;
  font-size: 18px;
  letter-spacing: -0.02em;
}
.bad-cases__title svg { color: var(--danger); }
.bad-cases__count {
  min-width: 20px;
  padding: 0 6px;
  border-radius: 999px;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: 10.5px;
  font-weight: 700;
  text-align: center;
  line-height: 1.8;
}
.bad-cases__hint { margin: 0; color: var(--text-4); font-size: 11.5px; }
.bad-cases__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
}
.bad-case {
  padding: 13px 14px;
  border: 1px solid var(--danger-border);
  border-radius: var(--radius-sm);
  background: linear-gradient(180deg, #fff, #fffbfb);
}
.bad-case__head { display: flex; align-items: center; gap: 7px; }
.bad-case__id {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--text-2);
  background: var(--surface-3);
  padding: 1px 5px;
  border-radius: 4px;
}
.bad-case__label {
  font-size: 10px;
  font-weight: 700;
  color: var(--danger);
  background: var(--danger-soft);
  border: 1px solid var(--danger-border);
  padding: 0 6px;
  border-radius: 4px;
  line-height: 1.7;
}
.bad-case__latency { margin-left: auto; font-family: var(--font-mono); font-size: 9.5px; color: var(--text-4); }
.bad-case__input { margin: 8px 0 0; font-size: 12.5px; font-weight: 600; line-height: 1.6; color: var(--text); }
.bad-case__failures { margin: 8px 0 0; padding-left: 18px; }
.bad-case__failures li { color: #b42318; font-size: 11.5px; line-height: 1.7; }
.bad-case__failures-empty { margin: 8px 0 0; color: var(--text-4); font-size: 11.5px; }
.bad-case__reply { margin-top: 9px; }
.bad-case__reply summary {
  font-size: 10.5px;
  color: var(--text-3);
  cursor: pointer;
  user-select: none;
  width: fit-content;
}
.bad-case__reply summary:hover { color: var(--brand-700); }
.bad-case__reply pre {
  margin: 7px 0 0;
  padding: 8px 10px;
  max-height: 160px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: #fff;
  font-family: var(--font-mono);
  font-size: 10px;
  line-height: 1.65;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.bad-cases__empty {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--success-border);
  border-radius: var(--radius-sm);
  background: var(--success-soft);
  color: #05603a;
}
.bad-cases__empty b { font-size: 13px; }
.bad-cases__empty p { margin: 2px 0 0; font-size: 11.5px; color: #067647; line-height: 1.65; }
</style>
