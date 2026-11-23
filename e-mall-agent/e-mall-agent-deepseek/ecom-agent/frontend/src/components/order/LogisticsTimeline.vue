<template>
  <div class="logistics">
    <div class="logistics__head">
      <span class="logistics__company">{{ logistics?.company || '物流信息' }}</span>
      <span v-if="logistics?.trackingNo" class="logistics__tracking mono">{{ logistics.trackingNo }}</span>
      <el-tag v-if="logistics?.status" size="small" effect="plain">{{ logistics.status }}</el-tag>
    </div>
    <p v-if="logistics?.latestEvent" class="logistics__latest">最新：{{ logistics.latestEvent }}</p>

    <el-timeline v-if="events.length" class="logistics__timeline">
      <el-timeline-item
        v-for="(event, index) in events"
        :key="`${event.time}-${index}`"
        :timestamp="formatDateTime(event.time)"
        :type="index === 0 ? 'primary' : 'info'"
        :hollow="index !== 0"
        placement="top"
      >
        <span :class="{ 'text-strong': index === 0 }">{{ event.desc }}</span>
      </el-timeline-item>
    </el-timeline>
    <EmptyState v-else title="暂无物流轨迹" description="发货后可查看详细轨迹" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { LogisticsVO } from '@/types'
import { formatDateTime } from '@/utils/format'
import EmptyState from '@/components/common/EmptyState.vue'

const props = defineProps<{ logistics: LogisticsVO | null }>()

const events = computed(() => props.logistics?.events ?? [])
</script>

<style scoped lang="scss">
.logistics {
  &__head {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  &__company {
    font-size: 14px;
    font-weight: 600;
  }

  &__tracking {
    font-size: 12px;
    color: var(--ecom-text-secondary);
  }

  &__latest {
    margin: 6px 0 12px;
    padding: 6px 10px;
    font-size: 12px;
    color: #92400e;
    background: #fffbeb;
    border-radius: 6px;
  }

  &__timeline {
    padding-left: 4px;
  }
}
</style>
