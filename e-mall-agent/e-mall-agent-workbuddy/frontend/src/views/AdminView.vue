<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { audit, traces } from '../api/client'
import { useAppStore } from '../stores/app'
import type { AuditEntry, TraceEvent } from '../types'

const store = useAppStore()
const accounts = [
  { username: '张三', role: 'customer', label: '普通客户' },
  { username: '王客服', role: 'service', label: '客服专员' },
  { username: '管理员', role: 'admin', label: '系统管理员' },
]

const allPermissions = [
  'product:read', 'chat:use', 'order:read', 'order:create', 'order:refund',
  'order:manage', 'audit:read', 'trace:read', 'user:manage',
]

const matrix: Record<string, string[]> = {
  customer: ['product:read', 'chat:use', 'order:read', 'order:create', 'order:refund'],
  service: ['product:read', 'chat:use', 'order:read', 'order:refund', 'order:manage', 'audit:read', 'trace:read'],
  admin: allPermissions,
}

const roleLabels: Record<string, string> = { customer: '普通客户', service: '客服专员', admin: '管理员' }

const traceRows = ref<TraceEvent[]>([])
const auditRows = ref<AuditEntry[]>([])
const traceNotice = ref('')
const auditNotice = ref('')
const loggingIn = ref('')
const loginError = ref('')

function formatTime(value: string | number): string {
  if (typeof value === 'number') {
    const date = new Date(value * 1000)
    return date.toLocaleString('zh-CN', { hour12: false })
  }
  return String(value).replace('T', ' ').replace(/\+.*$/, '')
}

function payloadText(value: unknown): string {
  const text = JSON.stringify(value)
  return text && text.length > 100 ? `${text.slice(0, 100)}...` : text || '-'
}

async function loadData(): Promise<void> {
  traceNotice.value = ''
  auditNotice.value = ''
  traceRows.value = []
  auditRows.value = []

  try {
    traceRows.value = await traces(50)
  } catch (err) {
    traceNotice.value = err instanceof Error ? err.message : '追踪数据加载失败'
  }
  try {
    auditRows.value = await audit(50)
  } catch (err) {
    auditNotice.value = err instanceof Error ? err.message : '审计日志加载失败'
  }
}

async function switchRole(username: string): Promise<void> {
  loggingIn.value = username
  loginError.value = ''
  try {
    await store.login(username, '123456')
    await loadData()
  } catch (err) {
    loginError.value = err instanceof Error ? err.message : '登录失败'
  } finally {
    loggingIn.value = ''
  }
}

function doLogout(): void {
  store.logout()
  traceRows.value = []
  auditRows.value = []
  traceNotice.value = ''
  auditNotice.value = ''
}

onMounted(() => {
  if (store.isLoggedIn) void loadData()
})
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2 class="section-title">观测与权限</h2>
        <p class="small muted">切换角色验证 RBAC 权限边界，查看调用链追踪与审计记录</p>
      </div>
      <div v-if="store.isLoggedIn" class="current-user">
        <span class="badge badge-blue">{{ store.user?.name }} / {{ roleLabels[store.user?.role || ''] || store.user?.role }}</span>
        <button class="btn btn-sm" type="button" @click="doLogout">退出登录</button>
      </div>
    </div>

    <div v-if="loginError" class="notice error">{{ loginError }}</div>

    <section class="card login-card">
      <div class="block-head">
        <h3 class="block-title">角色切换登录</h3>
        <span class="small muted">演示密码统一为 123456</span>
      </div>
      <div class="role-buttons">
        <button
          v-for="account in accounts"
          :key="account.username"
          class="role-button"
          :class="{ active: store.user?.name === account.username }"
          type="button"
          :disabled="loggingIn !== ''"
          @click="switchRole(account.username)"
        >
          <span class="role-name">{{ account.username }}</span>
          <span class="small muted">{{ account.label }} / {{ account.role }}</span>
        </button>
      </div>
      <div v-if="store.user" class="permission-strip">
        <span class="small muted">当前权限：</span>
        <span v-for="permission in store.user.permissions" :key="permission" class="badge badge-green">{{ permission }}</span>
      </div>
    </section>

    <section class="card matrix-card">
      <div class="block-head">
        <h3 class="block-title">权限矩阵</h3>
        <span class="small muted">与后端 RBAC 配置一致</span>
      </div>
      <div class="table-scroll">
        <table class="data-table">
          <thead>
            <tr>
              <th>权限</th>
              <th v-for="account in accounts" :key="account.role">{{ account.label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="permission in allPermissions" :key="permission">
              <td class="mono small">{{ permission }}</td>
              <td v-for="account in accounts" :key="account.role">
                <span class="badge" :class="matrix[account.role].includes(permission) ? 'badge-green' : 'badge'">
                  {{ matrix[account.role].includes(permission) ? '允许' : '禁止' }}
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="tables-grid">
      <section class="card table-card">
        <div class="block-head">
          <h3 class="block-title">调用链追踪</h3>
          <span class="badge">{{ traceRows.length }} 条</span>
        </div>
        <div v-if="traceNotice" class="notice">{{ traceNotice }}</div>
        <div v-else-if="traceRows.length === 0" class="empty-state">暂无追踪记录，先在对话页发起一次提问</div>
        <div v-else class="table-scroll">
          <table class="data-table compact">
            <thead>
              <tr><th>时间</th><th>Trace ID</th><th>节点</th><th>事件</th><th>Payload</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in traceRows" :key="index">
                <td class="small muted">{{ formatTime(row.ts) }}</td>
                <td class="mono small">{{ row.trace_id.slice(0, 8) }}</td>
                <td class="small">{{ row.node }}</td>
                <td class="small">{{ row.event }}</td>
                <td class="mono small payload">{{ payloadText(row.payload) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="card table-card">
        <div class="block-head">
          <h3 class="block-title">审计日志</h3>
          <span class="badge">{{ auditRows.length }} 条</span>
        </div>
        <div v-if="auditNotice" class="notice">{{ auditNotice }}</div>
        <div v-else-if="auditRows.length === 0" class="empty-state">暂无审计记录</div>
        <div v-else class="table-scroll">
          <table class="data-table compact">
            <thead>
              <tr><th>时间</th><th>操作者</th><th>动作</th><th>资源</th><th>决策</th><th>详情</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in auditRows" :key="index">
                <td class="small muted">{{ formatTime(row.ts) }}</td>
                <td class="small">{{ row.actor }}</td>
                <td class="mono small">{{ row.action }}</td>
                <td class="small">{{ row.resource }}</td>
                <td><span class="badge" :class="row.decision === 'allow' ? 'badge-green' : 'badge-red'">{{ row.decision }}</span></td>
                <td class="small muted">{{ row.detail || '-' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page { max-width: 1280px; }
.page-head { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 18px; }
.page-head p { margin-top: 4px; }
.current-user { display: flex; align-items: center; gap: 10px; }
.notice { padding: 10px 14px; border-radius: 8px; margin: 0 16px 14px; font-size: 12px; background: #fff8ea; color: #92400e; }
.notice.error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.login-card, .matrix-card, .table-card { padding: 16px 18px; margin-bottom: 18px; }
.block-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.role-buttons { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.role-button { display: flex; flex-direction: column; gap: 3px; align-items: flex-start; padding: 12px 14px; border: 1px solid #dce1ea; border-radius: 9px; background: #fbfcfe; cursor: pointer; text-align: left; }
.role-button:hover { border-color: #9dbdf5; background: #f4f8ff; }
.role-button.active { border-color: #2563eb; background: #eef4ff; }
.role-name { font-size: 14px; font-weight: 600; }
.permission-strip { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #eef0f4; }
.table-scroll { overflow-x: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.data-table th { text-align: left; font-weight: 500; color: #6b7280; background: #fafbfd; padding: 10px 12px; border-bottom: 1px solid #eef0f4; white-space: nowrap; }
.data-table td { padding: 10px 12px; border-bottom: 1px solid #f1f3f6; white-space: nowrap; }
.data-table tr:last-child td { border-bottom: none; }
.data-table.compact { font-size: 12px; }
.payload { max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.tables-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(440px, 1fr)); gap: 18px; }
.tables-grid .table-card { margin-bottom: 0; }
</style>
