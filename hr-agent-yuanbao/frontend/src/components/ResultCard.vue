<script setup>
defineProps({
  answer: { type: String, default: '' },
  mode: { type: String, default: '' },
  traceId: { type: String, default: '' },
})
</script>

<template>
  <section class="card result-card">
    <div class="card-head">
      <h3>最终回答</h3>
      <div class="badges">
        <span class="badge" :class="mode === 'ollama' ? 'badge-green' : 'badge-amber'">
          {{ mode === 'ollama' ? '● Ollama 真实模型' : '● 离线演示 Mock' }}
        </span>
        <span class="badge badge-ghost" v-if="traceId">trace {{ traceId }}</span>
      </div>
    </div>
    <div class="answer-text">{{ answer || '（暂无结果，点击左侧章节后运行）' }}</div>
    <p class="hint" v-if="mode === 'mock'">
      当前为离线演示模式：流程、状态机、审批、Trace 全部真实执行，模型应答由教学脚手架提供。
      安装 Ollama 并拉取模型后自动切换为真实推理。
    </p>
  </section>
</template>
