import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/layout/index.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '工作台', icon: 'DataBoard', perm: 'dashboard:view' },
      },
      {
        path: 'system/user',
        name: 'UserManage',
        component: () => import('@/views/system/UserManage.vue'),
        meta: { title: '用户管理', icon: 'User', perm: 'user:list' },
      },
      {
        path: 'system/role',
        name: 'RoleManage',
        component: () => import('@/views/system/RoleManage.vue'),
        meta: { title: '角色管理', icon: 'UserFilled', perm: 'role:list' },
      },
      {
        path: 'system/permission',
        name: 'PermissionManage',
        component: () => import('@/views/system/PermissionManage.vue'),
        meta: { title: '权限管理', icon: 'Lock', perm: 'permission:list' },
      },
      {
        path: 'system/audit',
        name: 'AuditLog',
        component: () => import('@/views/system/AuditLog.vue'),
        meta: { title: '审计日志', icon: 'Document', perm: 'audit:list' },
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const store = useUserStore()
  if (!store.token) return { path: '/login', query: { redirect: to.fullPath } }
  if (!store.loaded) {
    try {
      await store.fetchProfile()
    } catch {
      store.logout()
      return { path: '/login' }
    }
  }
  const perm = to.meta.perm as string | undefined
  if (perm && !store.hasPerm(perm)) {
    ElMessage.error('没有访问该页面的权限')
    return { path: '/dashboard' }
  }
  return true
})

router.afterEach((to) => {
  document.title = `${to.meta.title ?? '管理系统'} · Admin Scaffold`
})

export default router
