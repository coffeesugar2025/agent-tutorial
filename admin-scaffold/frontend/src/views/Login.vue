<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { loginApi } from '@/api'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: 'admin', password: 'Admin@123' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const data = await loginApi({ username: form.username, password: form.password })
    store.setToken(data.access_token)
    await store.fetchProfile()
    ElMessage.success('登录成功')
    router.push((route.query.redirect as string) || '/')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <div class="brand">
        <el-icon :size="28"><Setting /></el-icon>
        <h1>Admin Scaffold</h1>
        <p class="text-muted">FastAPI + Vue3 管理系统</p>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="密码"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-button type="primary" class="submit" :loading="loading" @click="submit">
          登 录
        </el-button>
      </el-form>
      <p class="tip text-muted">默认账号 admin / Admin@123，首次登录后请立即修改</p>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100%; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b5b8c 60%, #409eff 100%);
}
.login-card {
  width: 400px; padding: 36px 32px; background: #fff;
  border-radius: 12px; box-shadow: 0 12px 40px rgba(0, 0, 0, 0.2);
}
.brand { text-align: center; margin-bottom: 28px; color: #303133; }
.brand h1 { font-size: 22px; margin: 8px 0 4px; }
.brand p { margin: 0; }
.submit { width: 100%; margin-top: 4px; }
.tip { text-align: center; margin: 18px 0 0; }
</style>
