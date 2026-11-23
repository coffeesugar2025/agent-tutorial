<template>
  <div class="page">
    <PageHeader title="设置" description="切换 Python / Java 后端，查看接口基地址、能力探测与依赖健康">
      <el-button size="small" type="primary" :loading="ui.capabilitiesLoading || healthLoading" @click="refresh">
        重新探测
      </el-button>
    </PageHeader>

    <div class="settings-grid">
      <div class="panel">
        <div class="panel__header">
          <span class="panel__title">后端连接</span>
          <span class="panel__subtitle">顶栏切换器与这里共用同一份状态</span>
        </div>
        <BackendSwitcher />

        <el-descriptions :column="1" border size="small" class="mt-12">
          <el-descriptions-item label="后端预设">{{ ui.backendLabel }}</el-descriptions-item>
          <el-descriptions-item label="API 基地址">
            <span class="mono">{{ ui.apiBase }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="后端版本">{{ versionText }}</el-descriptions-item>
          <el-descriptions-item label="服务状态">
            <el-tag size="small" :type="healthTone" effect="plain">{{ healthText }}</el-tag>
          </el-descriptions-item>
        </el-descriptions>

        <p class="settings-hint">Token 按 API 基地址隔离存储，切换后端后需要在新后端重新登录。</p>
      </div>

      <div class="panel">
        <div class="panel__header">
          <span class="panel__title">能力探测</span>
          <span class="panel__subtitle">GET /meta/capabilities</span>
        </div>
        <DataState
          :loading="ui.capabilitiesLoading"
          :error="ui.capabilitiesError"
          :empty="!capabilities"
          empty-text="暂无能力信息"
          @retry="ui.loadCapabilities()"
        >
          <template v-if="capabilities">
            <div class="settings-tags">
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
            </div>
            <el-descriptions :column="1" border size="small" class="mt-12">
              <el-descriptions-item label="主模型">{{ capabilities.llm.primary }}</el-descriptions-item>
              <el-descriptions-item label="降级链">{{ fallbackText }}</el-descriptions-item>
            </el-descriptions>
          </template>
        </DataState>
      </div>
    </div>

    <div class="panel">
      <div class="panel__header">
        <span class="panel__title">依赖组件</span>
        <span class="panel__subtitle">GET /health（不在 /api/v1 前缀下）</span>
      </div>
      <DataState
        :loading="healthLoading"
        :error="healthError"
        :empty="!healthLoading && !healthError && !health"
        empty-text="未获取到健康信息"
        @retry="loadHealth"
      >
        <div v-if="health" class="settings-tags">
          <el-tag
            v-for="(value, name) in health.components"
            :key="name"
            size="small"
            :type="value === 'UP' ? 'success' : 'danger'"
            effect="plain"
          >
            {{ name }} · {{ value }}
          </el-tag>
        </div>
      </DataState>
    </div>

    <div class="panel">
      <div class="panel__header">
        <span class="panel__title">构建期配置</span>
        <span class="panel__subtitle">来自 .env（Vite 仅暴露 VITE_ 前缀）</span>
      </div>
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="VITE_API_BASE">{{ env.apiBase }}</el-descriptions-item>
        <el-descriptions-item label="VITE_PROXY_TARGET">{{ env.proxyTarget }}</el-descriptions-item>
        <el-descriptions-item label="Python 预设">{{ env.python }}</el-descriptions-item>
        <el-descriptions-item label="Java 预设">{{ env.java }}</el-descriptions-item>
      </el-descriptions>
      <p class="settings-hint">修改 .env 后需重启 dev server 或重新 build；运行期切换请使用上方切换器（写入 localStorage）。</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { getHealth } from '@/api/admin'
import type { HealthVO } from '@/types'
import type { TagTone } from '@/utils/format'
import { errorMessage } from '@/utils/guard'
import BackendSwitcher from '@/components/common/BackendSwitcher.vue'
import DataState from '@/components/common/DataState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const health = ref<HealthVO | null>(null)
const healthLoading = ref(false)
const healthError = ref('')

const env = {
  apiBase: import.meta.env.VITE_API_BASE || '/api',
  proxyTarget: import.meta.env.VITE_PROXY_TARGET || 'http://localhost:8000',
  python: import.meta.env.VITE_BACKEND_PYTHON || 'http://localhost:8000/api/v1',
  java: import.meta.env.VITE_BACKEND_JAVA || 'http://localhost:8080/api/v1',
}

const versionText = computed(() =>
  ui.capabilities ? `${ui.capabilities.backend} v${ui.capabilities.version}` : '未探测',
)
const capabilities = computed(() => ui.capabilities)
const fallbackText = computed(() => {
  const fallbacks = ui.capabilities?.llm.fallbacks ?? []
  return fallbacks.length > 0 ? fallbacks.join(' / ') : '无降级模型'
})
const healthText = computed(() => health.value?.status ?? '未知')
const healthTone = computed<TagTone>(() => {
  switch (health.value?.status) {
    case 'UP':
      return 'success'
    case 'DEGRADED':
      return 'warning'
    case 'DOWN':
      return 'danger'
    default:
      return 'info'
  }
})

async function loadHealth(): Promise<void> {
  healthLoading.value = true
  healthError.value = ''
  try {
    health.value = await getHealth()
  } catch (err) {
    healthError.value = errorMessage(err, '健康检查失败')
    health.value = null
  } finally {
    healthLoading.value = false
  }
}

function refresh(): void {
  void ui.loadCapabilities()
  void loadHealth()
}

onMounted(() => {
  if (!ui.capabilities && !ui.capabilitiesLoading) void ui.loadCapabilities()
  void loadHealth()
})
</script>

<style scoped lang="scss">
.settings-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

.settings-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;

  :deep(.el-tag.is-off) {
    opacity: 0.5;
  }
}

.settings-hint {
  margin: 12px 0 0;
  font-size: 12px;
  color: var(--ecom-text-secondary);
}

@media (max-width: 1100px) {
  .settings-grid {
    grid-template-columns: 1fr;
  }
}
</style>
