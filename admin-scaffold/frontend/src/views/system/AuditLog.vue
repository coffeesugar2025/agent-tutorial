<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { getAuditLogs, type AuditItem } from '@/api'

const rows = ref<AuditItem[]>([])
const total = ref(0)
const query = reactive({ page: 1, size: 10, keyword: '', action: '' })
const loading = ref(false)
const degraded = ref(false)

const actions = [
  { label: '全部', value: '' },
  { label: '登录', value: 'login' },
  { label: '退出', value: 'logout' },
  { label: '新增', value: 'create' },
  { label: '编辑', value: 'update' },
  { label: '删除', value: 'delete' },
]

async function load() {
  loading.value = true
  try {
    const data = await getAuditLogs(query)
    rows.value = data.items
    total.value = data.total
    degraded.value = data.total === 0
  } finally {
    loading.value = false
  }
}

function fmt(ts: string) {
  return ts ? ts.replace('T', ' ').slice(0, 19) : '-'
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="搜索操作详情 / 用户 / 资源" clearable style="width: 260px" @keyup.enter="query.page = 1; load()" />
      <el-select v-model="query.action" style="width: 140px">
        <el-option v-for="a in actions" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
      <el-button type="primary" @click="query.page = 1; load()">搜索</el-button>
      <span class="text-muted">数据来源：Elasticsearch 索引 admin-audit</span>
    </div>

    <el-alert
      v-if="degraded && !loading"
      type="info"
      :closable="false"
      show-icon
      title="暂无日志"
      description="请确认 Elasticsearch 已连接且已有写操作；组件离线时业务不受影响，但审计日志不会被记录。"
      style="margin-bottom: 16px"
    />

    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column label="时间" width="180"><template #default="{ row }">{{ fmt(row.ts) }}</template></el-table-column>
      <el-table-column prop="username" label="操作人" width="120" />
      <el-table-column prop="action" label="动作" width="100">
        <template #default="{ row }"><el-tag size="small">{{ row.action }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="resource" label="资源" width="120" />
      <el-table-column prop="detail" label="详情" min-width="220" />
      <el-table-column prop="ip" label="IP" width="140" />
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page" v-model:page-size="query.size"
        :total="total" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next"
        @change="load"
      />
    </div>
  </div>
</template>
