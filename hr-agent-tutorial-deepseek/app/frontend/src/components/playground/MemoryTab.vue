<script setup>
import { computed } from 'vue'
import AppIcon from '../AppIcon.vue'
import EmptyState from '../ui/EmptyState.vue'

const props = defineProps({
  memory: { type: Object, default: null },
  usage: { type: Object, default: null },
})

const employee = computed(() => props.memory?.employee || null)
const facts = computed(() => (Array.isArray(props.memory?.facts) ? props.memory.facts : []))
const initials = computed(() => (employee.value?.name ? employee.value.name.slice(-1) : '员'))

const usageRows = computed(() => {
  const data = props.usage
  if (!data) return []
  return [
    { label: '输入 tokens', value: data.prompt_tokens },
    { label: '输出 tokens', value: data.completion_tokens },
    { label: '合计 tokens', value: data.total_tokens },
    { label: '本次成本', value: formatCost(data.cost_usd) },
  ].filter((row) => row.value !== undefined && row.value !== null)
})

function formatCost(value) {
  const number = Number(value)
  if (!Number.isFinite(number)) return value
  return number < 0.01 ? `$${number.toFixed(6)}` : `$${number.toFixed(4)}`
}

function factText(fact) {
  if (typeof fact === 'string') return fact
  if (fact && typeof fact === 'object') {
    return fact.text || fact.content || fact.value || JSON.stringify(fact)
  }
  return String(fact ?? '')
}
</script>

<template>
  <div class="memory-tab">
    <template v-if="employee">
      <div class="profile">
        <span class="profile__avatar" aria-hidden="true">{{ initials }}</span>
        <div class="profile__main">
          <div class="profile__name">
            {{ employee.name || '演示员工' }}
            <span class="profile__id">{{ employee.id || employee.employee_id || '—' }}</span>
          </div>
          <div class="profile__tags">
            <span v-if="employee.department" class="chip chip--xs">{{ employee.department }}</span>
            <span v-if="employee.city" class="chip chip--xs">{{ employee.city }}</span>
            <span v-if="employee.title" class="chip chip--xs">{{ employee.title }}</span>
          </div>
        </div>
      </div>
    </template>

    <div v-else class="memory-empty">
      <EmptyState
        icon="user"
        title="暂无员工画像"
        message="发送第一条消息后，后端会返回当前演示身份的画像与本次会话提取的事实。"
      />
    </div>

    <section v-if="employee" class="facts" aria-labelledby="facts-title">
      <div class="facts__head">
        <h3 id="facts-title" class="facts__title">
          <AppIcon name="chip" :size="14" />
          会话事实
          <span class="facts__count">{{ facts.length }}</span>
        </h3>
        <span class="facts__hint">带来源与时效，生产环境需分级</span>
      </div>

      <ul v-if="facts.length" class="facts__list">
        <li v-for="(fact, index) in facts" :key="index" class="fact">
          <span class="fact__index">{{ String(index + 1).padStart(2, '0') }}</span>
          <span class="fact__text">{{ factText(fact) }}</span>
        </li>
      </ul>
      <p v-else class="facts__empty">本次会话还没有写入新事实。</p>
    </section>

    <section v-if="usageRows.length" class="usage" aria-labelledby="usage-title">
      <h3 id="usage-title" class="usage__title">本次调用消耗</h3>
      <div class="usage__grid">
        <div v-for="row in usageRows" :key="row.label" class="usage__item">
          <span class="usage__label">{{ row.label }}</span>
          <span class="usage__value">{{ row.value }}</span>
        </div>
      </div>
    </section>

    <p class="memory-note">
      记忆只用于演示：生产环境需要租户隔离、TTL、PII 分级与「是否允许长期保存」的用户授权（见第 06、12 章）。
    </p>
  </div>
</template>

<style scoped>
.memory-tab { padding: 14px; }
.profile {
  display: flex;
  align-items: center;
  gap: 11px;
  padding: 13px;
  border: 1px solid var(--border);
  border-radius: 12px;
  background: linear-gradient(130deg, #fff, #f8f8ff);
}
.profile__avatar {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: 12px;
  background: var(--brand);
  color: #fff;
  font-size: 17px;
  font-weight: 700;
  flex: none;
  box-shadow: 0 8px 18px -12px rgba(79, 70, 229, 0.9);
}
.profile__main { min-width: 0; }
.profile__name {
  display: flex;
  align-items: baseline;
  gap: 7px;
  font-size: 14.5px;
  font-weight: 650;
  color: var(--text);
}
.profile__id {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 500;
  color: var(--brand-700);
  background: var(--brand-50);
  padding: 1px 5px;
  border-radius: 4px;
}
.profile__tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
.memory-empty { margin-top: 4px; }
.facts { margin-top: 16px; }
.facts__head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.facts__title {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 0;
  font-size: 12px;
  font-weight: 650;
  color: var(--text-2);
}
.facts__title svg { color: var(--brand); }
.facts__count {
  min-width: 17px;
  padding: 0 5px;
  border-radius: 999px;
  background: var(--brand-50);
  color: var(--brand-700);
  font-size: 9.5px;
  text-align: center;
  line-height: 1.7;
}
.facts__hint { font-size: 9.5px; color: var(--text-4); }
.facts__list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
.fact {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-2);
  font-size: 11.5px;
  line-height: 1.65;
  color: var(--text-2);
}
.fact__index { font-family: var(--font-mono); font-size: 9.5px; color: var(--text-4); flex: none; line-height: 1.85; }
.fact__text { overflow-wrap: anywhere; }
.facts__empty { margin: 0; padding: 10px 12px; border: 1px dashed var(--border-strong); border-radius: 8px; color: var(--text-4); font-size: 11.5px; }
.usage { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border); }
.usage__title { margin: 0 0 8px; font-size: 12px; font-weight: 650; color: var(--text-2); }
.usage__grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.usage__item {
  display: flex;
  flex-direction: column;
  gap: 1px;
  padding: 7px 10px;
  border-radius: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.usage__label { font-size: 9.5px; color: var(--text-4); }
.usage__value { font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--text); }
.memory-note {
  margin: 16px 2px 0;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
  color: var(--text-4);
  font-size: 10px;
  line-height: 1.7;
}
</style>
