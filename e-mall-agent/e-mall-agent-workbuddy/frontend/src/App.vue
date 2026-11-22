<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { useAppStore } from './stores/app'

const store = useAppStore()
const route = useRoute()
const router = useRouter()

const pageTitle = computed(() => (route.meta.title as string) || '控制台')

const navItems = [
  { path: '/chat', label: '智能对话', icon: 'chat' },
  { path: '/products', label: '商品目录', icon: 'grid' },
  { path: '/orders', label: '订单管理', icon: 'list' },
  { path: '/workflow', label: '工作流', icon: 'flow' },
  { path: '/admin', label: '观测与权限', icon: 'shield' },
]

const roleLabels: Record<string, string> = {
  customer: '普通客户',
  service: '客服专员',
  admin: '管理员',
  guest: '未登录',
}

onMounted(() => {
  if (store.isLoggedIn) {
    store.loadMe().catch(() => { /* keep token, profile can be loaded later */ })
  }
})

function doLogout(): void {
  store.logout()
  router.push('/chat')
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">E</div>
        <div>
          <div class="brand-name">电商智能助手</div>
          <div class="brand-sub">AGENT CONSOLE</div>
        </div>
      </div>

      <nav class="nav">
        <RouterLink
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          active-class="active"
        >
          <svg v-if="item.icon === 'chat'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9 9 0 0 1-3.4-.6L3 21l1.7-5.1A8.4 8.4 0 0 1 12 3.1a8.4 8.4 0 0 1 9 8.4Z"/></svg>
          <svg v-else-if="item.icon === 'grid'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
          <svg v-else-if="item.icon === 'list'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>
          <svg v-else-if="item.icon === 'flow'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="2" y="4" width="6" height="5" rx="1"/><rect x="16" y="4" width="6" height="5" rx="1"/><rect x="9" y="15" width="6" height="5" rx="1"/><path d="M8 6.5h8M5 9v4h7v2M19 9v4h-3"/></svg>
          <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M12 3 4 6v6c0 5 3.4 8.4 8 9 4.6-.6 8-4 8-9V6l-8-3Z"/><path d="m9 12 2 2 4-4"/></svg>
          <span>{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-foot">
        <div class="user-card">
          <div class="avatar">{{ store.user ? store.user.name.slice(0, 1) : '访' }}</div>
          <div class="user-meta">
            <div class="user-name">{{ store.user ? store.user.name : '未登录' }}</div>
            <div class="user-role">{{ roleLabels[store.user?.role || ''] || store.user?.role || '访客' }}</div>
          </div>
          <button v-if="store.isLoggedIn" class="link-button" type="button" @click="doLogout">退出</button>
          <RouterLink v-else to="/admin" class="link-button">登录</RouterLink>
        </div>
      </div>
    </aside>

    <section class="main">
      <header class="topbar">
        <div class="topbar-left">
          <h1>{{ pageTitle }}</h1>
          <span class="topbar-divider"></span>
          <span class="crumb">电商智能助手 / {{ pageTitle }}</span>
        </div>
        <div class="topbar-right">
          <span class="status-dot"></span>
          <span class="status-text">服务运行中</span>
          <span class="role-chip">{{ roleLabels[store.user?.role || ''] || (store.isLoggedIn ? store.user?.role : '访客') }}</span>
        </div>
      </header>

      <main class="content">
        <RouterView />
      </main>
    </section>
  </div>
</template>

<style>
:root {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
  color: #1f2937;
  background: #f5f7fb;
  font-synthesis: none;
  text-rendering: optimizeLegibility;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  background: #f5f7fb;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.5;
}

h1, h2, h3, h4, p { margin: 0; }
button, input, textarea, select { font: inherit; color: inherit; }
a { color: inherit; text-decoration: none; }

.card {
  background: #fff;
  border: 1px solid #e6e9ef;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.03);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 14px;
  border: 1px solid #d7dce5;
  border-radius: 8px;
  background: #fff;
  color: #374151;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  font-size: 13px;
}
.btn:hover { background: #f3f5f9; border-color: #c4cad6; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-primary { background: #2563eb; border-color: #2563eb; color: #fff; }
.btn-primary:hover:not(:disabled) { background: #1d4ed8; border-color: #1d4ed8; }
.btn-danger { color: #dc2626; border-color: #f1c9c9; }
.btn-danger:hover:not(:disabled) { background: #fef2f2; }
.btn-sm { padding: 5px 10px; font-size: 12px; }

.input, .textarea, .select {
  width: 100%;
  padding: 8px 11px;
  border: 1px solid #d9dee7;
  border-radius: 8px;
  background: #fff;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.input:focus, .textarea:focus, .select:focus {
  border-color: #93b4f7;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  background: #eef2f7;
  color: #475569;
}
.badge-blue { background: #e8f0ff; color: #1d4ed8; }
.badge-green { background: #e7f7ee; color: #15803d; }
.badge-amber { background: #fff5e0; color: #b45309; }
.badge-red { background: #feecea; color: #c0392b; }
.badge-purple { background: #f1eaff; color: #7c3aed; }

.section-title { font-size: 15px; font-weight: 600; color: #1f2937; }
.muted { color: #6b7280; }
.small { font-size: 12px; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

.empty-state {
  padding: 32px 16px;
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
}
</style>

<style scoped>
.layout { display: flex; min-height: 100vh; }

.sidebar {
  width: 232px;
  flex: 0 0 232px;
  background: #fff;
  border-right: 1px solid #e6e9ef;
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
}

.brand { display: flex; align-items: center; gap: 11px; padding: 22px 20px 18px; }
.brand-mark {
  width: 34px; height: 34px; border-radius: 9px;
  background: linear-gradient(135deg, #3b82f6, #1d4ed8);
  color: #fff; display: grid; place-items: center;
  font-weight: 700; font-size: 17px;
}
.brand-name { font-weight: 650; font-size: 15px; letter-spacing: 0.2px; }
.brand-sub { font-size: 10px; color: #9ca3af; letter-spacing: 1.2px; margin-top: 1px; }

.nav { display: flex; flex-direction: column; gap: 3px; padding: 6px 12px; }
.nav-item {
  display: flex; align-items: center; gap: 11px;
  padding: 10px 12px; border-radius: 8px;
  color: #5b6472; font-size: 13.5px;
  transition: background 0.15s, color 0.15s;
}
.nav-item svg { width: 18px; height: 18px; flex: 0 0 18px; }
.nav-item:hover { background: #f4f6fa; color: #1f2937; }
.nav-item.active { background: #ebf2ff; color: #1d4ed8; font-weight: 600; }

.sidebar-foot { margin-top: auto; padding: 14px 14px 18px; border-top: 1px solid #eef0f4; }
.user-card { display: flex; align-items: center; gap: 9px; }
.avatar {
  width: 32px; height: 32px; border-radius: 50%;
  background: #e8f0ff; color: #1d4ed8;
  display: grid; place-items: center; font-weight: 600; flex: 0 0 32px;
}
.user-meta { min-width: 0; flex: 1; }
.user-name { font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.user-role { font-size: 11px; color: #9ca3af; }
.link-button {
  background: none; border: none; color: #2563eb;
  font-size: 12px; cursor: pointer; padding: 4px;
}

.main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.topbar {
  height: 64px; flex: 0 0 64px;
  background: #fff; border-bottom: 1px solid #e6e9ef;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 28px; position: sticky; top: 0; z-index: 10;
}
.topbar-left { display: flex; align-items: center; gap: 12px; }
.topbar-left h1 { font-size: 17px; font-weight: 650; }
.topbar-divider { width: 1px; height: 16px; background: #e3e6ec; }
.crumb { font-size: 12px; color: #9ca3af; }
.topbar-right { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #6b7280; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; background: #22c55e; box-shadow: 0 0 0 3px #e7f7ee; }
.role-chip {
  margin-left: 8px; padding: 3px 10px; border-radius: 999px;
  background: #f2f4f8; color: #475569; font-weight: 500;
}
.content { flex: 1; padding: 24px 28px 32px; min-width: 0; }

@media (max-width: 860px) {
  .layout { flex-direction: column; }
  .sidebar { width: 100%; flex: none; height: auto; position: static; border-right: none; border-bottom: 1px solid #e6e9ef; }
  .brand { padding: 12px 16px; }
  .nav { flex-direction: row; overflow-x: auto; padding: 4px 10px 10px; }
  .nav-item { white-space: nowrap; }
  .sidebar-foot { padding: 8px 14px 12px; }
  .topbar { padding: 0 16px; }
  .content { padding: 16px; }
}
</style>
