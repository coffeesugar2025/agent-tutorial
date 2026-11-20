<script setup>
import { computed } from 'vue'

const props = defineProps({ steps: { type: Array, default: () => [] } })

const TYPE_META = {
  thought:     { label: '思考', cls: 't-thought' },
  action:      { label: '动作', cls: 't-action' },
  observation: { label: '观察', cls: 't-obs' },
  plan:        { label: '计划', cls: 't-plan' },
  tool:        { label: '工具', cls: 't-tool' },
  llm:         { label: '模型', cls: 't-llm' },
  state:       { label: '状态', cls: 't-state' },
  hitl:        { label: '人工', cls: 't-hitl' },
  memory:      { label: '记忆', cls: 't-memory' },
  retrieve:    { label: '检索', cls: 't-retrieve' },
  error:       { label: '错误', cls: 't-error' },
}

const normalized = computed(() =>
  props.steps.map((s, i) => ({
    ...s,
    idx: i + 1,
    meta: TYPE_META[s.type] || { label: s.type, cls: 't-default' },
    metaText: s.meta && Object.keys(s.meta).length ? JSON.stringify(s.meta, null, 2) : '',
  })),
)
</script>

<template>
  <section class="card">
    <div class="card-head">
      <h3>Trace 时间线</h3>
      <span class="sub">{{ steps.length }} 步</span>
    </div>
    <div class="timeline">
      <div v-if="!steps.length" class="empty">运行一个 Demo 后，这里会显示 Agent 的每一步决策。</div>
      <div v-for="s in normalized" :key="s.idx" class="tl-item">
        <div class="tl-rail"><span class="tl-dot" :class="s.meta.cls"></span></div>
        <div class="tl-body">
          <div class="tl-line">
            <span class="tl-idx">{{ String(s.idx).padStart(2, '0') }}</span>
            <span class="chip" :class="s.meta.cls">{{ s.meta.label }}</span>
            <span class="tl-time">{{ s.ts }}</span>
          </div>
          <div class="tl-content" :class="{ 'is-error': s.type === 'error' }">{{ s.content }}</div>
          <details v-if="s.metaText" class="tl-meta">
            <summary>元数据</summary>
            <pre>{{ s.metaText }}</pre>
          </details>
        </div>
      </div>
    </div>
  </section>
</template>
