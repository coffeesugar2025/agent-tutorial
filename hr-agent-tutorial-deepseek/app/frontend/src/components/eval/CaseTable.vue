<script setup>
import { ref } from 'vue'
import AppIcon from '../AppIcon.vue'

defineProps({
  cases: { type: Array, default: () => [] },
  emptyMessage: { type: String, default: '没有符合筛选条件的用例。' },
})

const expandedId = ref('')

function toggle(id) {
  expandedId.value = expandedId.value === id ? '' : id
}

function failureText(failures) {
  if (!Array.isArray(failures) || !failures.length) return ''
  return failures.join('；')
}

function onRowKeydown(event, id) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    toggle(id)
  }
}
</script>

<template>
  <div class="case-table-wrap">
    <table v-if="cases.length" class="case-table">
      <caption class="sr-only">Golden Case 评测用例明细</caption>
      <thead>
        <tr>
          <th scope="col" class="col-id">用例</th>
          <th scope="col" class="col-result">结果</th>
          <th scope="col">检查项</th>
          <th scope="col" class="col-num">延迟</th>
          <th scope="col" class="col-num">tokens</th>
          <th scope="col">失败原因</th>
          <th scope="col" class="col-expand"><span class="sr-only">展开详情</span></th>
        </tr>
      </thead>
      <tbody>
        <template v-for="item in cases" :key="item.id">
          <tr
            class="case-row"
            :class="{ 'is-failed': !item.passed, 'is-open': expandedId === item.id }"
            tabindex="0"
            :aria-expanded="expandedId === item.id"
            @click="toggle(item.id)"
            @keydown="onRowKeydown($event, item.id)"
          >
            <td class="col-id">
              <span class="case-id">{{ item.id }}</span>
              <span class="case-input" :title="item.input">{{ item.input }}</span>
            </td>
            <td class="col-result">
              <span class="badge" :class="item.passed ? 'badge--success' : 'badge--danger'">
                <AppIcon :name="item.passed ? 'check' : 'close'" :size="11" />
                {{ item.passed ? '通过' : '失败' }}
              </span>
            </td>
            <td>
              <span class="checks">
                <span class="check" :class="item.intent_ok ? 'check--ok' : 'check--bad'" :title="`意图判断${item.intent_ok ? '正确' : '错误'}`">
                  <AppIcon :name="item.intent_ok ? 'check-circle' : 'alert-circle'" :size="12" />
                  意图
                </span>
                <span class="check" :class="item.tools_ok ? 'check--ok' : 'check--bad'" :title="`工具调用${item.tools_ok ? '正确' : '错误'}`">
                  <AppIcon :name="item.tools_ok ? 'check-circle' : 'alert-circle'" :size="12" />
                  工具
                </span>
                <span class="check" :class="item.must_include_ok ? 'check--ok' : 'check--bad'" :title="`必含内容${item.must_include_ok ? '命中' : '缺失'}`">
                  <AppIcon :name="item.must_include_ok ? 'check-circle' : 'alert-circle'" :size="12" />
                  必含
                </span>
              </span>
            </td>
            <td class="col-num">{{ item.latency_ms ?? '—' }} ms</td>
            <td class="col-num">{{ item.tokens ?? '—' }}</td>
            <td class="col-reason">
              <span v-if="item.failures?.length" class="failure">
                {{ failureText(item.failures) }}
              </span>
              <span v-else class="muted">—</span>
            </td>
            <td class="col-expand">
              <AppIcon name="chevron-down" :size="14" class="expand-icon" :class="{ 'is-open': expandedId === item.id }" />
            </td>
          </tr>

          <tr v-if="expandedId === item.id" class="detail-row">
            <td colspan="7">
              <div class="detail">
                <div class="detail__head">
                  <span class="detail__id">{{ item.id }}</span>
                  <span class="detail__input">{{ item.input }}</span>
                </div>
                <div v-if="item.failures?.length" class="detail__failures">
                  <span class="detail__label">失败原因</span>
                  <ul>
                    <li v-for="(failure, index) in item.failures" :key="index">{{ failure }}</li>
                  </ul>
                </div>
                <div class="detail__reply">
                  <span class="detail__label">Agent 回复</span>
                  <pre>{{ item.reply || '（无回复）' }}</pre>
                </div>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>

    <p v-else class="case-empty">{{ emptyMessage }}</p>
  </div>
</template>

<style scoped>
.case-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: #fff;
}
.case-table {
  width: 100%;
  min-width: 860px;
  border-collapse: collapse;
  font-size: 12.5px;
}
.case-table th {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-3);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-align: left;
  white-space: nowrap;
}
.case-table td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
  color: var(--text-2);
}
.case-table tbody tr:last-child td { border-bottom: 0; }
.case-row { cursor: pointer; transition: background-color 0.13s ease; }
.case-row:hover { background: #fafaff; }
.case-row:focus-visible { outline: 2px solid rgba(79, 70, 229, 0.4); outline-offset: -2px; }
.case-row.is-failed { background: #fffbfb; }
.case-row.is-failed:hover { background: #fff6f5; }
.case-row.is-open { background: var(--brand-50); }
.case-row.is-open td { border-bottom-color: transparent; }
.col-id { min-width: 260px; }
.col-result { width: 74px; }
.col-num { white-space: nowrap; font-family: var(--font-mono); font-size: 10.5px; }
.col-reason { min-width: 160px; max-width: 240px; }
.col-expand { width: 32px; text-align: right; }
.case-id {
  display: inline-block;
  margin-right: 7px;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--surface-3);
  color: var(--text-2);
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  line-height: 1.8;
  vertical-align: 1px;
}
.case-input {
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: var(--text-2);
  line-height: 1.65;
}
.checks { display: inline-flex; flex-wrap: wrap; gap: 6px; }
.check {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 9.5px;
  font-weight: 600;
  white-space: nowrap;
}
.check--ok { color: var(--success); }
.check--bad { color: var(--danger); }
.failure {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  color: #b42318;
  font-size: 11px;
  line-height: 1.6;
}
.expand-icon { color: var(--text-4); transition: transform 0.16s ease; }
.expand-icon.is-open { transform: rotate(180deg); color: var(--brand); }
.detail-row td { padding: 0; background: #fbfbff; border-bottom: 1px solid var(--border); }
.detail { padding: 13px 16px 15px; border-left: 2px solid var(--brand); }
.detail__head { display: flex; align-items: baseline; gap: 7px; flex-wrap: wrap; }
.detail__id {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  color: var(--brand-700);
  background: var(--brand-50);
  padding: 1px 5px;
  border-radius: 4px;
}
.detail__input { font-size: 12.5px; font-weight: 600; color: var(--text); }
.detail__label {
  display: block;
  margin: 10px 0 4px;
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.05em;
  color: var(--text-4);
  text-transform: uppercase;
}
.detail__failures ul { margin: 0; padding-left: 18px; }
.detail__failures li { color: #b42318; font-size: 11.5px; line-height: 1.7; }
.detail__reply pre {
  margin: 0;
  padding: 10px 12px;
  max-height: 220px;
  overflow: auto;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: #fff;
  font-family: var(--font-mono);
  font-size: 10.5px;
  line-height: 1.7;
  color: var(--text-2);
  white-space: pre-wrap;
  word-break: break-word;
}
.case-empty { margin: 0; padding: 28px 16px; text-align: center; color: var(--text-4); font-size: 12px; }
</style>
