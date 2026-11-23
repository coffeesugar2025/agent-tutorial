<template>
  <div class="backend-switcher">
    <div class="backend-switcher__row">
      <span class="status-dot" :class="statusClass" :title="statusTitle" />
      <el-select
        :model-value="ui.backendId"
        size="small"
        class="backend-switcher__select"
        @change="onSelect"
      >
        <el-option
          v-for="option in ui.backendOptions"
          :key="option.id"
          :label="option.label"
          :value="option.id"
        />
        <el-option label="自定义后端…" value="custom" />
      </el-select>
      <el-tooltip :content="`当前基地址：${ui.apiBase}`" placement="bottom">
        <span class="backend-switcher__base mono">{{ shortBase }}</span>
      </el-tooltip>
      <el-tooltip content="重新探测 /meta/capabilities" placement="bottom">
        <el-button size="small" text :loading="ui.capabilitiesLoading" @click="ui.loadCapabilities()">
          ⟳
        </el-button>
      </el-tooltip>
    </div>

    <div class="backend-switcher__tags">
      <template v-if="ui.capabilityTags.length">
        <el-tag
          v-for="tag in ui.capabilityTags"
          :key="tag.key"
          size="small"
          :type="tag.enabled ? 'success' : 'info'"
          effect="plain"
          :class="{ 'is-off': !tag.enabled }"
        >
          {{ tag.label }}
        </el-tag>
        <el-tooltip v-if="ui.llmLabel" :content="`LLM：${ui.llmLabel}`" placement="bottom">
          <span class="backend-switcher__llm mono">{{ ui.capabilities?.llm.primary }}</span>
        </el-tooltip>
      </template>
      <el-tooltip v-else-if="ui.capabilitiesError" :content="ui.capabilitiesError" placement="bottom">
        <el-tag size="small" type="danger" effect="plain">能力探测失败</el-tag>
      </el-tooltip>
      <span v-else class="backend-switcher__pending">探测能力中…</span>
    </div>

    <el-dialog v-model="customVisible" title="自定义后端地址" width="440px" append-to-body>
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="API 基地址">
          <el-input v-model="customBase" placeholder="http://localhost:9000/api/v1" clearable />
        </el-form-item>
      </el-form>
      <p class="backend-switcher__hint">需包含 <code>/api/v1</code> 前缀；跨域访问时后端需开启 CORS。</p>
      <template #footer>
        <el-button @click="cancelCustom">取消</el-button>
        <el-button type="primary" :disabled="!customBase.trim()" @click="applyCustom">切换</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { BackendId } from '@/types'

const ui = useUiStore()
const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const customVisible = ref(false)
const customBase = ref(ui.apiBase)

const shortBase = computed(() => ui.apiBase.replace(/^https?:\/\//, ''))
const statusClass = computed(() => {
  if (ui.capabilities) return 'is-ok'
  return ui.capabilitiesError ? 'is-error' : 'is-pending'
})
const statusTitle = computed(() => {
  if (ui.capabilities) {
    return `后端在线：${ui.capabilities.backend} v${ui.capabilities.version}`
  }
  return ui.capabilitiesError || '能力探测中'
})

function labelFor(id: BackendId): string {
  return ui.backendOptions.find((option) => option.id === id)?.label ?? '自定义后端'
}

function applyBackend(id: BackendId, base?: string): void {
  const selection = ui.switchBackend(id, base)
  auth.syncForBackend()

  if (!auth.isLoggedIn) {
    ElMessage.info(`已切换到 ${labelFor(id)}，请先登录`)
    const redirect = route.name === 'login' ? undefined : route.fullPath
    void router.replace({ name: 'login', query: redirect ? { redirect } : {} })
    return
  }

  ElMessage.success(`已切换到 ${labelFor(id)}（${selection.base}），正在重新加载数据`)
  // 切换后端后所有页面数据都需要重取，整页刷新最稳妥
  window.setTimeout(() => window.location.reload(), 300)
}

function onSelect(value: BackendId): void {
  if (value === 'custom') {
    customBase.value = ui.apiBase
    customVisible.value = true
    return
  }
  if (value === ui.backendId) return
  applyBackend(value)
}

function applyCustom(): void {
  const base = customBase.value.trim()
  if (!/^(https?:\/\/|\/)/i.test(base)) {
    ElMessage.warning('地址需以 http:// 或 / 开头')
    return
  }
  customVisible.value = false
  applyBackend('custom', base)
}

function cancelCustom(): void {
  customVisible.value = false
}
</script>

<style scoped lang="scss">
.backend-switcher {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;

  &__row {
    display: flex;
    align-items: center;
    gap: 6px;
  }

  &__select {
    width: 148px;
  }

  &__base {
    max-width: 190px;
    overflow: hidden;
    font-size: 11px;
    color: var(--ecom-text-secondary);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__tags {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    align-items: center;
  }

  &__llm {
    padding: 0 4px;
    font-size: 11px;
    color: var(--ecom-text-secondary);
    background: var(--el-fill-color-light);
    border-radius: 4px;
  }

  &__pending {
    font-size: 11px;
    color: var(--ecom-text-secondary);
  }

  &__hint {
    margin: 0;
    font-size: 12px;
    color: var(--ecom-text-secondary);

    code {
      padding: 0 3px;
      background: var(--el-fill-color-light);
      border-radius: 3px;
    }
  }

  :deep(.el-tag.is-off) {
    opacity: 0.5;
  }
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
  flex-shrink: 0;

  &.is-ok {
    background: var(--ecom-success);
    box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15);
  }

  &.is-error {
    background: var(--ecom-danger);
  }

  &.is-pending {
    background: var(--ecom-warning);
  }
}

@media (max-width: 1100px) {
  .backend-switcher__base {
    display: none;
  }
}
</style>
