<script setup lang="ts">
import type { HealthInfo } from '../types'

defineProps<{ health: HealthInfo | null; toolCount: number }>()
</script>

<template>
  <div class="badges">
    <span class="badge live" v-if="health">● {{ health.status === 'ok' ? '服务在线' : '服务异常' }}</span>
    <span class="badge" v-else>● 连接中</span>
    <span class="badge">LangChain {{ health?.langchain_version ?? '1.5' }}</span>
    <span class="badge mock" v-if="health">
      {{ health.agent_mode === 'mock' ? '离线演示模式' : health.model }}
    </span>
    <span class="badge">MCP · {{ health?.mcp_transport ?? 'stdio' }}</span>
    <span class="badge">{{ toolCount || health?.tool_count || 0 }} 个工具</span>
  </div>
</template>
