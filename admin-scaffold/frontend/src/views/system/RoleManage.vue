<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  assignPermissions, createRole, deleteRole, getPermissionTree, getRoles,
  updateRole, type PermGroup, type RoleItem,
} from '@/api'

const rows = ref<RoleItem[]>([])
const total = ref(0)
const query = reactive({ page: 1, size: 10, keyword: '' })
const loading = ref(false)

const dialog = reactive({ visible: false, title: '', id: 0 })
const form = reactive({ code: '', name: '', description: '', is_active: true })

const permDialog = reactive({ visible: false, roleId: 0, roleCode: '', checked: [] as number[], groups: [] as PermGroup[] })

async function load() {
  loading.value = true
  try {
    const data = await getRoles(query)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.id = 0
  dialog.title = '新增角色'
  Object.assign(form, { code: '', name: '', description: '', is_active: true })
  dialog.visible = true
}

function openEdit(row: RoleItem) {
  dialog.id = row.id
  dialog.title = `编辑角色 - ${row.code}`
  Object.assign(form, {
    code: row.code, name: row.name,
    description: row.description, is_active: row.is_active,
  })
  dialog.visible = true
}

async function save() {
  if (!form.code || !form.name) {
    ElMessage.warning('请填写角色编码与名称')
    return
  }
  if (dialog.id) await updateRole(dialog.id, { ...form })
  else await createRole({ ...form, permission_ids: [] })
  ElMessage.success('保存成功')
  dialog.visible = false
  await load()
}

async function remove(row: RoleItem) {
  await ElMessageBox.confirm(`确认删除角色「${row.name}」？`, '提示', { type: 'warning' })
  await deleteRole(row.id)
  ElMessage.success('已删除')
  await load()
}

async function openPerm(row: RoleItem) {
  const groups = await getPermissionTree()
  permDialog.groups = groups
  permDialog.checked = [...row.permission_ids]
  permDialog.roleId = row.id
  permDialog.roleCode = row.code
  permDialog.visible = true
}

async function savePerm() {
  await assignPermissions(permDialog.roleId, permDialog.checked)
  ElMessage.success('权限已分配')
  permDialog.visible = false
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="角色编码 / 名称" clearable style="width: 240px" @keyup.enter="load" />
      <el-button type="primary" @click="query.page = 1; load()">搜索</el-button>
      <el-button v-permission="'role:create'" type="success" @click="openCreate">新增角色</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="code" label="角色编码" min-width="140" />
      <el-table-column prop="name" label="角色名称" min-width="140" />
      <el-table-column prop="description" label="描述" min-width="180" />
      <el-table-column label="权限数" width="90">
        <template #default="{ row }"><el-tag size="small">{{ row.permission_ids.length }}</el-tag></template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button v-permission="'role:update'" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-permission="'role:update'" link type="warning" @click="openPerm(row)">分配权限</el-button>
          <el-button v-permission="'role:delete'" link type="danger" @click="remove(row)">删除</el-button>
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
        <el-form-item label="角色编码"><el-input v-model="form.code" :disabled="!!dialog.id" placeholder="如 ops_admin" /></el-form-item>
        <el-form-item label="角色名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="禁用" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="permDialog.visible" :title="`分配权限 - ${permDialog.roleCode}`" width="620px">
      <el-checkbox-group v-model="permDialog.checked">
        <div v-for="g in permDialog.groups" :key="g.module" class="perm-group">
          <div class="perm-title">{{ g.module }}</div>
          <el-checkbox v-for="p in g.children" :key="p.id" :value="p.id" style="margin-right: 18px">
            {{ p.name }} <span class="text-muted">{{ p.code }}</span>
          </el-checkbox>
        </div>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="permDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="savePerm">保存分配</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.perm-group { margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid #ebeef5; }
.perm-title { font-weight: 600; margin-bottom: 8px; color: #409eff; }
</style>
