import { createRouter, createWebHistory } from 'vue-router'

// 页面按路由懒加载，首屏只加载首页所需代码。
const routes = [
  {
    path: '/',
    name: 'home',
    component: () => import('./pages/HomePage.vue'),
    meta: { title: 'HR Agent 学堂 · 从 HR 痛点到可交付的 Agent' },
  },
  {
    path: '/learn/:slug',
    name: 'learn',
    component: () => import('./pages/LearnPage.vue'),
    meta: { title: '学习 · HR Agent 学堂' },
  },
  {
    path: '/playground',
    name: 'playground',
    component: () => import('./pages/PlaygroundPage.vue'),
    meta: { title: 'HR Agent 工作台 · HR Agent 学堂' },
  },
  {
    path: '/eval',
    name: 'eval',
    component: () => import('./pages/EvalPage.vue'),
    meta: { title: '评测看板 · HR Agent 学堂' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('./pages/NotFoundPage.vue'),
    meta: { title: '页面未找到 · HR Agent 学堂' },
  },
]

const router = createRouter({
  // 使用 history 模式；后端需把非 /api 的未知路径回退到 index.html。
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    if (to.hash) return { el: to.hash, top: 88, behavior: 'smooth' }
    return { top: 0 }
  },
})

router.afterEach((to) => {
  document.title = to.meta?.title || 'HR Agent 学堂'
})

export default router
