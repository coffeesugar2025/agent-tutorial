<template>
  <aside class="session-list">
    <div class="session-list__head">
      <span class="session-list__title">会话</span>
      <el-button size="small" type="primary" plain @click="emit('create')">+ 新建</el-button>
    </div>

    <DataState
      class="session-list__state"
      :loading="loading"
      :error="error"
      :empty="sessions.length === 0"
      empty-text="还没有会话"
      empty-description="新建会话后即可开始对话"
      :rows="3"
      @retry="emit('refresh')"
    >
      <ul class="session-list__items">
        <li
          v-for="session in sessions"
          :key="session.id"
          class="session-item"
          :class="{ 'is-active': session.id === activeId }"
          @click="emit('select', session.id)"
        >
          <div class="session-item__main">
            <div class="session-item__title ellipsis">{{ session.title || '未命名会话' }}</div>
            <div class="session-item__meta">
              <AgentBadge :agent="session.agentType" compact />
              <span class="session-item__time">{{ fromNow(session.lastMessageAt || session.createdAt) }}</span>
            </div>
          </div>
          <button type="button" class="session-item__del" title="删除会话" @click.stop="confirmRemove(session)">
            ✕
          </button>
        </li>
      </ul>
    </DataState>
  </aside>
</template>

<script setup lang="ts">
import { ElMessageBox } from 'element-plus'
import type { SessionVO } from '@/types'
import { fromNow } from '@/utils/format'
import AgentBadge from './AgentBadge.vue'
import DataState from '@/components/common/DataState.vue'

withDefaults(
  defineProps<{
    sessions: SessionVO[]
    activeId: number | null
    loading?: boolean
    error?: string
  }>(),
  { loading: false, error: '' },
)

const emit = defineEmits<{
  create: []
  select: [sessionId: number]
  remove: [sessionId: number]
  refresh: []
}>()

async function confirmRemove(session: SessionVO): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除会话「${session.title || '未命名会话'}」？该操作不可恢复。`, '删除会话', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
    emit('remove', session.id)
  } catch {
    /* 用户取消 */
  }
}
</script>

<style scoped lang="scss">
.session-list {
  display: flex;
  flex-direction: column;
  width: 264px;
  padding: 12px;
  background: #fff;
  border: 1px solid var(--ecom-border);
  border-radius: var(--ecom-radius, 10px);
  flex-shrink: 0;
  min-height: 0;

  &__head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
    flex-shrink: 0;
  }

  &__title {
    font-size: 13px;
    font-weight: 600;
    color: var(--ecom-text-primary);
  }

  &__state {
    flex: 1;
    overflow: auto;
    min-height: 0;
  }

  &__items {
    margin: 0;
    padding: 0;
    list-style: none;
  }
}

.session-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  margin-bottom: 4px;
  cursor: pointer;
  border-radius: 8px;

  &:hover {
    background: #f4f6fb;
  }

  &.is-active {
    background: #eaf0ff;

    .session-item__title {
      color: var(--ecom-primary);
    }
  }

  &__main {
    flex: 1;
    min-width: 0;
  }

  &__title {
    font-size: 13px;
    color: var(--ecom-text-primary);
  }

  &__meta {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 4px;
  }

  &__time {
    font-size: 11px;
    color: var(--ecom-text-placeholder);
  }

  &__del {
    width: 20px;
    height: 20px;
    padding: 0;
    font-size: 11px;
    color: var(--ecom-text-placeholder);
    cursor: pointer;
    visibility: hidden;
    background: transparent;
    border: 0;
    border-radius: 4px;

    &:hover {
      color: var(--ecom-danger);
      background: #fef2f2;
    }
  }

  &:hover &__del {
    visibility: visible;
  }
}
</style>
