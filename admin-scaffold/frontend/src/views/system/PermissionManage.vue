<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createPermission, deletePermission, getPermissions, updatePermission,
  type PermissionItem,
} from '@/api'

const rows = ref<PermissionItem[]>([])
const total = ref(0)
const query = reactive({ page: 1, size: 10, keyword: '', module: '' })
const loading = ref(false)
const dialog = reactive({ visible: false, title: '', id: 0 })
const form = reactive({ code: '', name: '', module: 'system', kind: 'api', sort: 0 })

async function load() {
  loading.value = true
  try {
    const data = await getPermissions(query)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.id = 0
  dialog.title = '新增权限'
  Object.assign(form, { code: '', name: '', module: 'system', kind: 'api', sort: 0 })
  dialog.visible = true
}

function openEdit(row: PermissionItem) {
  dialog.id = row.id
  dialog.title = `编辑权限 - ${row.code}`
  Object.assign(form, {
    code: row.code, name: row.name, module: row.module, kind: row.kind, sort: row.sort,
  })
  dialog.visible = true
}

async function save() {
  if (!form.code || !form.name) {
    ElMessage.warning('请填写权限编码与名称')
    return
  }
  if (dialog.id) await updatePermission(dialog.id, { ...form })
  else await createPermission({ ...form })
  ElMessage.success('保存成功')
  dialog.visible = false
  await load()
}

async function remove(row: PermissionItem) {
  await ElMessageBox.confirm(`确认删除权限「${row.code}」？`, '提示', { type: 'warning' })
  await deletePermission(row.id)
  ElMessage.success('已删除')
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="权限编码 / 名称" clearable style="width: 220px" @keyup.enter="load" />
      <el-input v-model="query.module" placeholder="模块，如 user" clearable style="width: 180px" @keyup.enter="load" />
      <el-button type="primary" @click="query.page = 1; load()">搜索</el-button>
      <el-button v-permission="'permission:create'" type="success" @click="openCreate">新增权限</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="code" label="权限编码" min-width="180" />
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="module" label="模块" min-width="120" />
      <el-table-column prop="kind" label="类型" width="100" />
      <el-table-column prop="sort" label="排序" width="80" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button v-permission="'permission:update'" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-permission="'permission:delete'" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="query.page" v-model:page-size="query.size"
        :total="total" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next"
        @change="load"
      />
    </div>

    <el-dialog v-model="dialog.visible" :title="dialog.title" width="480px">
      <el-form label-width="90px">
        <el-form-item label="权限编码"><el-input v-model="form.code" :disabled="!!dialog.id" placeholder="如 report:export" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="模块"><el-input v-model="form.module" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.kind" style="width: 100%">
            <el-option label="菜单 menu" value="menu" />
            <el-option label="接口 api" value="api" />
            <el-option label="按钮 button" value="button" />
          </el-select>
        </el-form-item>
        <el-form-item label="排序"><el-input-number v-model="form.sort" :min="0" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
