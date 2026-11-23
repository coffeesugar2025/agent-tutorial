<template>
  <div class="layout" :class="{ 'layout--collapsed': ui.sidebarCollapsed }">
    <aside class="layout__aside">
      <div class="brand" @click="goChat">
        <span class="brand__logo">EC</span>
        <span v-if="!ui.sidebarCollapsed" class="brand__text">
          <strong>电商智能体</strong>
          <small>Console</small>
        </span>
      </div>

      <el-menu
        :default-active="route.path"
        :collapse="ui.sidebarCollapsed"
        :collapse-transition="false"
        class="layout__menu"
        router
      >
        <el-menu-item v-for="item in visibleMenus" :key="item.path" :index="item.path">
          <span class="menu-glyph" :data-key="item.key">{{ item.glyph }}</span>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-menu>

      <div v-if="!ui.sidebarCollapsed" class="layout__aside-footer">
        <span class="layout__version">{{ ui.capabilities?.backend ?? 'backend' }} · v{{ ui.capabilities?.version ?? '—' }}</span>
      </div>
    </aside>

    <div class="layout__body">
      <header class="layout__header">
        <div class="layout__header-left">
          <button class="collapse-btn" type="button" :title="ui.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'" @click="ui.toggleSidebar()">
            {{ ui.sidebarCollapsed ? '»' : '«' }}
          </button>
          <h1 class="layout__title">{{ route.meta.title ?? '控制台' }}</h1>
        </div>

        <div class="layout__header-right">
          <BackendSwitcher />
          <el-dropdown trigger="click" @command="onUserCommand">
            <span class="user-chip">
              <span class="user-chip__avatar">{{ initials }}</span>
              <span class="user-chip__name">{{ auth.displayName }}</span>
              <span class="user-chip__caret">▾</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item disabled>
                  {{ auth.roles.length ? auth.roles.join(' / ') : '无角色' }}
                </el-dropdown-item>
                <el-dropdown-item command="settings" divided>设置</el-dropdown-item>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="layout__main scroll-area">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import BackendSwitcher from '@/components/common/BackendSwitcher.vue'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const auth = useAuthStore()
const chat = useChatStore()
const route = useRoute()
const router = useRouter()

interface MenuItem {
  path: string
  label: string
  key: string
  glyph: string
  roles?: string[]
}

const MENUS: MenuItem[] = [
  { path: '/chat', label: '智能对话', key: 'chat', glyph: '💬' },
  { path: '/products', label: '商品', key: 'products', glyph: '🛍' },
  { path: '/orders', label: '订单', key: 'orders', glyph: '📦' },
  { path: '/knowledge', label: '知识库', key: 'knowledge', glyph: '📚', roles: ['ADMIN', 'OPS'] },
  { path: '/observability', label: '可观测', key: 'observability', glyph: '📈', roles: ['ADMIN'] },
  { path: '/evals', label: '评测', key: 'evals', glyph: '🧪', roles: ['ADMIN'] },
  { path: '/settings', label: '设置', key: 'settings', glyph: '⚙' },
]

const visibleMenus = computed(() => MENUS.filter((item) => !item.roles || auth.hasAnyRole(item.roles)))

const initials = computed(() => {
  const name = auth.displayName
  return name ? name.slice(0, 1).toUpperCase() : 'U'
})

function goChat(): void {
  void router.push('/chat')
}

function onUserCommand(command: string): void {
  if (command === 'settings') {
    void router.push('/settings')
    return
  }
  if (command === 'logout') {
    chat.clearAll()
    auth.logout()
    ElMessage.success('已退出登录')
    void router.replace({ name: 'login' })
  }
}

onMounted(() => {
  if (!auth.user) void auth.fetchMe()
  if (!ui.capabilities) void ui.loadCapabilities()
})
</script>

<style scoped lang="scss">
.layout {
  display: flex;
  width: 100%;
  height: 100%;
  overflow: hidden;

  &__aside {
    display: flex;
    flex-direction: column;
    width: 224px;
    background: #0f172a;
    transition: width 0.2s ease;
    flex-shrink: 0;
  }

  &--collapsed &__aside {
    width: 64px;
  }

  &__body {
    display: flex;
    flex: 1;
    flex-direction: column;
    min-width: 0;
  }

  &__header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
    height: 64px;
    padding: 0 16px;
    background: #fff;
    border-bottom: 1px solid var(--ecom-border);
    flex-shrink: 0;
  }

  &__header-left {
    display: flex;
    align-items: center;
    gap: 10px;
    min-width: 0;
  }

  &__header-right {
    display: flex;
    align-items: center;
    gap: 14px;
  }

  &__title {
    margin: 0;
    overflow: hidden;
    font-size: 16px;
    font-weight: 600;
    color: var(--ecom-text-primary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__main {
    flex: 1;
    padding: 16px;
    background: var(--ecom-bg-page);
  }

  &__aside-footer {
    padding: 12px 16px;
    border-top: 1px solid rgba(148, 163, 184, 0.15);
  }

  &__version {
    font-size: 11px;
    color: #64748b;
  }
}

.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 64px;
  padding: 0 16px;
  cursor: pointer;
  flex-shrink: 0;

  &__logo {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    font-size: 13px;
    font-weight: 700;
    color: #fff;
    background: linear-gradient(135deg, #2f6bff, #6b93ff);
    border-radius: 9px;
    flex-shrink: 0;
  }

  &__text {
    display: flex;
    flex-direction: column;
    overflow: hidden;
    line-height: 1.25;
    white-space: nowrap;

    strong {
      font-size: 14px;
      color: #f1f5f9;
    }

    small {
      font-size: 10px;
      letter-spacing: 1px;
      color: #64748b;
      text-transform: uppercase;
    }
  }
}

.collapse-btn {
  width: 28px;
  height: 28px;
  padding: 0;
  font-size: 14px;
  color: var(--ecom-text-secondary);
  cursor: pointer;
  background: #f8fafc;
  border: 1px solid var(--ecom-border);
  border-radius: 6px;

  &:hover {
    color: var(--ecom-primary);
    border-color: var(--ecom-primary);
  }
}

.layout__menu {
  flex: 1;
  overflow-x: hidden;
  overflow-y: auto;
  border-right: none;
  background: transparent;

  :deep(.el-menu-item) {
    height: 44px;
    margin: 4px 8px;
    color: #c7d2e4;
    border-radius: 8px;

    &:hover {
      color: #fff;
      background: #1c2942;
    }

    &.is-active {
      color: #fff;
      background: var(--ecom-primary);
    }
  }

  :deep(.el-menu--collapse .el-menu-item) {
    justify-content: center;
    padding: 0 !important;
  }
}

.menu-glyph {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  margin-right: 10px;
  font-size: 14px;
  filter: grayscale(0.35);
}

.layout--collapsed .menu-glyph {
  margin-right: 0;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  cursor: pointer;
  border-radius: 8px;

  &:hover {
    background: #f4f6fb;
  }

  &__avatar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 28px;
    height: 28px;
    font-size: 12px;
    font-weight: 600;
    color: #fff;
    background: var(--ecom-primary);
    border-radius: 50%;
  }

  &__name {
    max-width: 120px;
    overflow: hidden;
    font-size: 13px;
    color: var(--ecom-text-primary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__caret {
    font-size: 10px;
    color: var(--ecom-text-secondary);
  }
}

@media (max-width: 900px) {
  .layout__aside {
    width: 64px;
  }

  .brand__text,
  .user-chip__name {
    display: none;
  }
}
</style>
