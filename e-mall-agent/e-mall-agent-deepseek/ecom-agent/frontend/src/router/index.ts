import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import DefaultLayout from '@/layouts/DefaultLayout.vue'
import { setUnauthorizedHandler } from '@/api/http'
import { useAuthStore } from '@/stores/auth'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    public?: boolean
    roles?: string[]
  }
}

const APP_TITLE = import.meta.env.VITE_APP_TITLE || '电商智能体控制台'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: DefaultLayout,
    redirect: '/chat',
    children: [
      {
        path: 'chat',
        name: 'chat',
        component: () => import('@/views/ChatView.vue'),
        meta: { title: '智能对话' },
      },
      {
        path: 'products',
        name: 'products',
        component: () => import('@/views/ProductsView.vue'),
        meta: { title: '商品' },
      },
      {
        path: 'orders',
        name: 'orders',
        component: () => import('@/views/OrdersView.vue'),
        meta: { title: '订单' },
      },
      {
        path: 'knowledge',
        name: 'knowledge',
        component: () => import('@/views/KnowledgeView.vue'),
        meta: { title: '知识库', roles: ['ADMIN', 'OPS'] },
      },
      {
        path: 'observability',
        name: 'observability',
        component: () => import('@/views/ObservabilityView.vue'),
        meta: { title: '可观测', roles: ['ADMIN'] },
      },
      {
        path: 'evals',
        name: 'evals',
        component: () => import('@/views/EvalView.vue'),
        meta: { title: '评测', roles: ['ADMIN'] },
      },
      {
        path: 'settings',
        name: 'settings',
        component: () => import('@/views/SettingsView.vue'),
        meta: { title: '设置' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/chat' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  auth.refreshFromStorage()

  if (to.meta.public) {
    if (to.name === 'login' && auth.isLoggedIn) return { name: 'chat' }
    return true
  }
  if (!auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!auth.user) {
    const restored = await auth.restore()
    if (!restored) return { name: 'login', query: { redirect: to.fullPath } }
  }
  const required = to.meta.roles
  if (required && required.length > 0 && !auth.hasAnyRole(required)) {
    ElMessage.warning('当前账号没有访问该页面的权限')
    return { name: 'chat' }
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · ${APP_TITLE}` : APP_TITLE
})

// 401 统一由 http 层回调，避免各处重复处理
setUnauthorizedHandler(() => {
  const auth = useAuthStore()
  const current = router.currentRoute.value
  auth.clear()
  if (current.name !== 'login') {
    void router.replace({ name: 'login', query: { redirect: current.fullPath } })
  }
})

export default router
