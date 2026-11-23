import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { getCapabilities } from '@/api/admin'
import { BACKEND_OPTIONS, getBackendSelection, setBackendSelection } from '@/api/http'
import type { BackendId, BackendOption, BackendSelection, CapabilitiesVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { readSidebarCollapsed, writeSidebarCollapsed } from '@/utils/storage'

export interface CapabilityTag {
  key: string
  label: string
  enabled: boolean
}

const CAPABILITY_LABELS: Array<{ key: string; label: string }> = [
  { key: 'mcp', label: 'MCP' },
  { key: 'skills', label: 'Skills' },
  { key: 'codeMode', label: 'CodeMode' },
  { key: 'text2sql', label: 'Text2SQL' },
  { key: 'hybridRag', label: 'HybridRAG' },
]

export const useUiStore = defineStore('ui', () => {
  const selection = ref<BackendSelection>(getBackendSelection())
  const backendOptions = ref<BackendOption[]>([...BACKEND_OPTIONS])
  const capabilities = ref<CapabilitiesVO | null>(null)
  const capabilitiesLoading = ref(false)
  const capabilitiesError = ref('')
  const sidebarCollapsed = ref(readSidebarCollapsed())

  const apiBase = computed(() => selection.value.base)
  const backendId = computed(() => selection.value.id)
  const backendLabel = computed(() => {
    const preset = backendOptions.value.find((option) => option.id === selection.value.id)
    return preset?.label ?? '自定义后端'
  })
  const capabilityTags = computed<CapabilityTag[]>(() => {
    const features = capabilities.value?.features
    if (!features) return []
    return CAPABILITY_LABELS.map(({ key, label }) => ({ key, label, enabled: features[key] === true }))
  })
  const llmLabel = computed(() => {
    const llm = capabilities.value?.llm
    if (!llm?.primary) return ''
    return llm.fallbacks.length ? `${llm.primary} → ${llm.fallbacks.join('/')}` : llm.primary
  })

  async function loadCapabilities(): Promise<void> {
    if (capabilitiesLoading.value) return
    capabilitiesLoading.value = true
    capabilitiesError.value = ''
    try {
      capabilities.value = await getCapabilities()
    } catch (err) {
      capabilities.value = null
      capabilitiesError.value = errorMessage(err, '能力探测失败')
    } finally {
      capabilitiesLoading.value = false
    }
  }

  /** 切换后端：写 localStorage（axios 拦截器即时生效）+ 重新探测能力 */
  function switchBackend(id: BackendId, base?: string): BackendSelection {
    selection.value = setBackendSelection(id, base)
    capabilities.value = null
    capabilitiesError.value = ''
    void loadCapabilities()
    return selection.value
  }

  function toggleSidebar(): void {
    sidebarCollapsed.value = !sidebarCollapsed.value
    writeSidebarCollapsed(sidebarCollapsed.value)
  }

  function setSidebarCollapsed(collapsed: boolean): void {
    sidebarCollapsed.value = collapsed
    writeSidebarCollapsed(collapsed)
  }

  return {
    selection,
    backendOptions,
    capabilities,
    capabilitiesLoading,
    capabilitiesError,
    sidebarCollapsed,
    apiBase,
    backendId,
    backendLabel,
    capabilityTags,
    llmLabel,
    loadCapabilities,
    switchBackend,
    toggleSidebar,
    setSidebarCollapsed,
  }
})
