<template>
  <div class="login">
    <div class="login__brand">
      <div class="login__logo">EC</div>
      <h1 class="login__title">电商智能体控制台</h1>
      <p class="login__subtitle">一套前端，同时对接 Python / Java 双后端</p>
      <ul class="login__features">
        <li><span>①</span> 多智能体路由：导购 / 客服 / 运营</li>
        <li><span>②</span> SSE 流式对话与工具调用可视化</li>
        <li><span>③</span> 高风险操作人工审批（HITL）</li>
        <li><span>④</span> 知识库检索调试与全链路可观测</li>
      </ul>
    </div>

    <div class="login__panel">
      <div class="login__card">
        <h2 class="login__card-title">登录</h2>
        <p class="login__card-desc">使用后端返回的 JWT 访问受保护资源</p>

        <el-alert
          v-if="auth.error"
          class="login__error"
          type="error"
          :closable="false"
          show-icon
          :title="auth.error"
        />

        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名" prop="username">
            <el-input v-model="form.username" size="large" placeholder="请输入用户名" autocomplete="username" />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              show-password
              placeholder="请输入密码"
              autocomplete="current-password"
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button class="login__submit" type="primary" size="large" :loading="auth.loading" @click="submit">
            登录
          </el-button>
        </el-form>

        <div class="login__backend">
          <span class="login__backend-label">当前后端</span>
          <BackendSwitcher />
        </div>
      </div>

      <p class="login__footer">
        账号由后端 seed 数据提供 · 双后端接口契约逐字节一致
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import BackendSwitcher from '@/components/common/BackendSwitcher.vue'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { LoginRequest } from '@/types'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()
const route = useRoute()

const formRef = ref<FormInstance>()
const form = reactive<LoginRequest>({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码至少 6 位', trigger: 'blur' },
  ],
}

async function submit(): Promise<void> {
  if (auth.loading) return
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  const ok = await auth.login({ username: form.username.trim(), password: form.password })
  if (!ok) return
  ElMessage.success('登录成功')
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/chat'
  await router.replace(redirect)
}

onMounted(() => {
  if (!ui.capabilities && !ui.capabilitiesLoading) void ui.loadCapabilities()
})
</script>

<style scoped lang="scss">
.login {
  display: flex;
  min-height: 100vh;
  background: #f5f7fb;

  &__brand {
    display: flex;
    flex: 1.1;
    flex-direction: column;
    justify-content: center;
    padding: 64px;
    color: #e2e8f0;
    background: radial-gradient(circle at 20% 20%, #1d4ed8 0%, #0f172a 60%);
  }

  &__logo {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 52px;
    height: 52px;
    margin-bottom: 20px;
    font-size: 18px;
    font-weight: 700;
    color: #fff;
    background: rgba(255, 255, 255, 0.15);
    border: 1px solid rgba(255, 255, 255, 0.25);
    border-radius: 14px;
  }

  &__title {
    margin: 0;
    font-size: 30px;
    font-weight: 600;
    letter-spacing: 1px;
  }

  &__subtitle {
    margin: 10px 0 32px;
    font-size: 14px;
    color: #94a3b8;
  }

  &__features {
    margin: 0;
    padding: 0;
    list-style: none;

    li {
      display: flex;
      align-items: center;
      gap: 10px;
      margin-bottom: 14px;
      font-size: 14px;
      color: #cbd5e1;

      span {
        color: #60a5fa;
      }
    }
  }

  &__panel {
    display: flex;
    flex: 1;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 40px 24px;
  }

  &__card {
    width: 100%;
    max-width: 400px;
    padding: 28px 32px;
    background: #fff;
    border-radius: 16px;
    box-shadow: 0 12px 40px rgba(15, 23, 42, 0.08);
  }

  &__card-title {
    margin: 0;
    font-size: 22px;
    font-weight: 600;
  }

  &__card-desc {
    margin: 6px 0 20px;
    font-size: 13px;
    color: var(--ecom-text-secondary);
  }

  &__error {
    margin-bottom: 14px;
  }

  &__submit {
    width: 100%;
    margin-top: 4px;
  }

  &__backend {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    padding-top: 16px;
    margin-top: 20px;
    border-top: 1px solid var(--ecom-border);
  }

  &__backend-label {
    padding-top: 4px;
    font-size: 12px;
    color: var(--ecom-text-secondary);
    white-space: nowrap;
  }

  &__footer {
    margin-top: 18px;
    font-size: 12px;
    color: var(--ecom-text-placeholder);
  }
}

@media (max-width: 900px) {
  .login__brand {
    display: none;
  }
}
</style>
