<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createUser, deleteUser, getRoleOptions, getUsers, resetPassword, updateUser,
  type UserItem,
} from '@/api'

const rows = ref<UserItem[]>([])
const total = ref(0)
const query = reactive({ page: 1, size: 10, keyword: '' })
const roleOptions = ref<{ id: number; code: string; name: string }[]>([])
const loading = ref(false)

const dialog = reactive({ visible: false, title: '', id: 0 })
const form = reactive({
  username: '', password: '', nickname: '', email: '', phone: '',
  is_active: true, role_ids: [] as number[],
})
const pwdDialog = reactive({ visible: false, id: 0, password: '' })

async function load() {
  loading.value = true
  try {
    const data = await getUsers(query)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialog.id = 0
  dialog.title = '新增用户'
  Object.assign(form, {
    username: '', password: '', nickname: '', email: '', phone: '',
    is_active: true, role_ids: [],
  })
  dialog.visible = true
}

function openEdit(row: UserItem) {
  dialog.id = row.id
  dialog.title = `编辑用户 - ${row.username}`
  Object.assign(form, {
    username: row.username, password: '', nickname: row.nickname,
    email: row.email, phone: row.phone, is_active: row.is_active,
    role_ids: [...row.role_ids],
  })
  dialog.visible = true
}

async function save() {
  if (!form.username || (!dialog.id && form.password.length < 6)) {
    ElMessage.warning('请填写用户名，新增时密码至少 6 位')
    return
  }
  const payload: Record<string, unknown> = {
    username: form.username, password: form.password, nickname: form.nickname,
    email: form.email, phone: form.phone, is_active: form.is_active,
    role_ids: form.role_ids,
  }
  if (dialog.id) {
    delete payload.password
    await updateUser(dialog.id, payload)
  } else {
    await createUser(payload)
  }
  ElMessage.success('保存成功')
  dialog.visible = false
  await load()
}

async function remove(row: UserItem) {
  await ElMessageBox.confirm(`确认删除用户「${row.username}」？`, '提示', { type: 'warning' })
  await deleteUser(row.id)
  ElMessage.success('已删除')
  await load()
}

function openPwd(row: UserItem) {
  pwdDialog.id = row.id
  pwdDialog.password = ''
  pwdDialog.visible = true
}

async function doReset() {
  if (pwdDialog.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  await resetPassword(pwdDialog.id, pwdDialog.password)
  ElMessage.success('密码已重置')
  pwdDialog.visible = false
}

onMounted(async () => {
  await load()
  try {
    roleOptions.value = await getRoleOptions()
  } catch {
    // 无角色列表权限时忽略
  }
})
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-input v-model="query.keyword" placeholder="用户名 / 昵称 / 邮箱" clearable style="width: 240px" @keyup.enter="load" />
      <el-button type="primary" @click="query.page = 1; load()">搜索</el-button>
      <el-button v-permission="'user:create'" type="success" @click="openCreate">新增用户</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="nickname" label="昵称" min-width="120" />
      <el-table-column prop="email" label="邮箱" min-width="160" />
      <el-table-column prop="phone" label="手机号" min-width="120" />
      <el-table-column label="角色" min-width="140">
        <template #default="{ row }">
          <el-tag v-for="r in row.roles" :key="r" size="small" style="margin-right: 4px">{{ r }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'info'" size="small">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button v-permission="'user:update'" link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-permission="'user:update'" link type="warning" @click="openPwd(row)">重置密码</el-button>
          <el-button v-permission="'user:delete'" link type="danger" @click="remove(row)">删除</el-button>
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

    <el-dialog v-model="dialog.visible" :title="dialog.title" width="520px">
      <el-form label-width="90px">
        <el-form-item label="用户名"><el-input v-model="form.username" :disabled="!!dialog.id" /></el-form-item>
        <el-form-item v-if="!dialog.id" label="初始密码"><el-input v-model="form.password" type="password" show-password /></el-form-item>
        <el-form-item label="昵称"><el-input v-model="form.nickname" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_ids" multiple style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.id" :label="`${r.name} (${r.code})`" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态"><el-switch v-model="form.is_active" active-text="启用" inactive-text="禁用" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwdDialog.visible" title="重置密码" width="400px">
      <el-input v-model="pwdDialog.password" type="password" show-password placeholder="新密码（至少 6 位）" />
      <template #footer>
        <el-button @click="pwdDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="doReset">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>
