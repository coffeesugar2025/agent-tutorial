<script setup lang="ts">
import { computed, markRaw, ref } from 'vue'
import CapabilityPanel from './CapabilityPanel.vue'
import ApprovalCenter from './ApprovalCenter.vue'
import TraceReplay from './TraceReplay.vue'
import EvalDashboard from './EvalDashboard.vue'
import CostDashboard from './CostDashboard.vue'
import CitationView from './CitationView.vue'

// markRaw：组件定义不要被 Vue 响应式包装（<component :is> 的官方要求）
const tabs = [
  { key: 'cap', label: '能力矩阵', comp: markRaw(CapabilityPanel) },
  { key: 'approve', label: '人工审批', comp: markRaw(ApprovalCenter) },
  { key: 'cite', label: '引用溯源', comp: markRaw(CitationView) },
  { key: 'trace', label: '轨迹回放', comp: markRaw(TraceReplay) },
  { key: 'eval', label: '评测看板', comp: markRaw(EvalDashboard) },
  { key: 'cost', label: '成本看板', comp: markRaw(CostDashboard) },
]
const active = ref<string>('cap')
const activeComp = computed(() => tabs.find(t => t.key === active.value)?.comp ?? tabs[0].comp)
</script>
<template>
  <section class="console">
    <nav class="tabs">
      <button v-for="t in tabs" :key="t.key" :class="{ on: active === t.key }"
              @click="active = t.key">{{ t.label }}</button>
    </nav>
    <div class="body"><component :is="activeComp" /></div>
  </section>
</template>
<style scoped>
.console { margin: 0 20px 16px; border: 1px solid #e3e8f0; border-radius: 12px; overflow: hidden; }
.tabs { display: flex; gap: 4px; padding: 8px; background: #f7f9fc; flex-wrap: wrap; }
.tabs button { border: 1px solid #cbd7ee; background: #fff; border-radius: 6px;
  padding: 5px 12px; font-size: 12px; cursor: pointer; }
.tabs button.on { background: #2b5cd9; color: #fff; border-color: #2b5cd9; }
.body { padding: 12px; max-height: 460px; overflow: auto; }
.body :deep(section.panel) { border: none; padding: 4px; }
</style>
