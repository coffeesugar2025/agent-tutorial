<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const activePath = computed(() => route.path)
// 后端按权限下发菜单，前端只做展示
const menus = computed(() => store.menus)
const username = computed(() => store.profile?.nickname || store.profile?.username || '未登录')

async function onCommand(cmd: string) {
  if (cmd === 'logout') {
    await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
    await store.logout()
    router.push('/login')
  }
}
</script>

<template>
  <el-container style="height: 100%">
    <el-aside width="220px" class="aside">
      <div class="logo">
        <el-icon><Setting /></el-icon>
        <span>Admin Scaffold</span>
      </div>
      <el-menu
        :default-active="activePath"
        router
        background-color="#1f2d3d"
        text-color="#bfcbd9"
        active-text-color="#409eff"
      >
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <span>{{ m.title }}</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="crumb">当前页面：{{ route.meta.title }}</div>
        <el-dropdown @command="onCommand">
          <span class="user">
            <el-icon><User /></el-icon>
            {{ username }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.aside { background: #1f2d3d; overflow-y: auto; }
.logo {
  height: 60px; display: flex; align-items: center; gap: 10px;
  padding: 0 20px; color: #fff; font-weight: 600; font-size: 15px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.aside :deep(.el-menu) { border-right: none; }
.header {
  background: #fff; display: flex; align-items: center;
  justify-content: space-between; box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.crumb { color: #606266; font-size: 14px; }
.user { display: flex; align-items: center; gap: 6px; cursor: pointer; color: #303133; }
</style>
