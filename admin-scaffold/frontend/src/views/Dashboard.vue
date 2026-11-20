<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { getHealth, type HealthState } from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const health = ref<HealthState>({
  mysql: false, redis: false, rabbitmq: false, kafka: false, elasticsearch: false,
})

const labels: Record<keyof HealthState, string> = {
  mysql: 'MySQL 主库',
  redis: 'Redis 缓存 / Token',
  rabbitmq: 'RabbitMQ 事件',
  kafka: 'Kafka 审计流',
  elasticsearch: 'Elasticsearch 检索',
}

onMounted(async () => {
  try {
    health.value = await getHealth()
  } catch {
    // 健康检查失败时保持全 false
  }
})
</script>

<template>
  <div>
    <el-card class="page-card" shadow="never">
      <h2 style="margin: 0 0 6px">欢迎回来，{{ store.profile?.nickname || store.profile?.username }}</h2>
      <p class="text-muted">
        角色：{{ store.profile?.roles.join('、') || '-' }} ｜ 已授予 {{ store.profile?.permissions.length || 0 }} 项权限
      </p>
    </el-card>

    <el-card class="page-card" shadow="never" style="margin-top: 16px">
      <template #header><strong>中间件连通状态</strong></template>
      <el-row :gutter="16">
        <el-col v-for="(label, key) in labels" :key="key" :xs="24" :sm="12" :md="8" style="margin-bottom: 12px">
          <div class="state-item">
            <el-tag :type="health[key as keyof HealthState] ? 'success' : 'danger'" effect="dark">
              {{ health[key as keyof HealthState] ? '在线' : '离线' }}
            </el-tag>
            <span style="margin-left: 10px">{{ label }}</span>
          </div>
        </el-col>
      </el-row>
      <p class="text-muted" style="margin-bottom: 0">
        除 MySQL 外的组件离线时服务会自动降级，登录与 CRUD 不受影响；审计日志需要 ES 才能检索。
      </p>
    </el-card>

    <el-card class="page-card" shadow="never" style="margin-top: 16px">
      <template #header><strong>脚手架能力</strong></template>
      <el-space wrap>
        <el-tag>JWT + Redis 黑名单</el-tag>
        <el-tag>RBAC 三级权限</el-tag>
        <el-tag>接口级 require_perm</el-tag>
        <el-tag>按钮级 v-permission</el-tag>
        <el-tag>ES 审计检索</el-tag>
        <el-tag>RabbitMQ 事件</el-tag>
        <el-tag>Kafka 消息流</el-tag>
        <el-tag>统一分页 CRUD</el-tag>
      </el-space>
    </el-card>
  </div>
</template>

<style scoped>
.state-item { display: flex; align-items: center; padding: 10px 0; font-size: 14px; }
</style>
