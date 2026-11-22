<script setup lang="ts">
import type { Session } from '../types'

defineProps<{ sessions: Session[]; activeId: string }>()
const emit = defineEmits<{ select: [id: string]; create: [] }>()

function selectSession(id: string) {
  emit('select', id)
}
function createSession() {
  emit('create')
}
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand-logo">栈</div>
      <div>
        <div class="brand-name">小栈智能体</div>
        <div class="brand-sub">Ecommerce Agent · v1.0</div>
      </div>
    </div>

    <button class="new-btn" @click="createSession">＋ <span>新建会话</span></button>

    <div class="side-label">会话列表</div>
    <div class="session-list">
      <button
        v-for="s in sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: s.id === activeId }"
        @click="selectSession(s.id)"
      >
        ◻ <span>{{ s.title }}</span>
      </button>
    </div>

    <div class="side-foot">
      每个会话对应一个 <code>thread_id</code><br />
      由 LangGraph Checkpointer 保存多轮记忆<br />
      工具经 <code>MCPAdapter</code> 动态发现
    </div>
  </aside>
</template>
