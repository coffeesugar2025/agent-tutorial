<template>
  <div class="index-jobs">
    <div class="panel__header">
      <span class="panel__title">索引任务</span>
      <span class="panel__subtitle">每 3 秒轮询进度</span>
    </div>

    <div v-for="job in jobs" :key="job.id" class="job-row">
      <div class="job-row__meta">
        <span class="mono">job #{{ job.id }}</span>
        <el-tag size="small" :type="metaOf(JOB_STATUS_META, job.status).tone" effect="plain">
          {{ metaOf(JOB_STATUS_META, job.status).label }}
        </el-tag>
        <span class="text-muted">{{ job.jobType }}</span>
        <span class="text-muted">doc {{ job.documentId || '—' }}</span>
        <span class="job-row__spacer" />
        <span class="text-muted">{{ job.progress }}%</span>
      </div>
      <el-progress :percentage="clamp(job.progress)" :status="progressStatus(job.status)" :stroke-width="6" />
      <div v-if="job.error" class="job-row__error">{{ job.error }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { IndexJobStatus, IndexJobVO } from '@/types'
import { JOB_STATUS_META, metaOf } from '@/utils/format'

defineProps<{ jobs: IndexJobVO[] }>()

function clamp(value: number): number {
  if (!Number.isFinite(value)) return 0
  return Math.min(100, Math.max(0, Math.round(value)))
}

function progressStatus(status: IndexJobStatus): '' | 'success' | 'exception' | 'warning' {
  if (status === 'SUCCESS') return 'success'
  if (status === 'FAILED' || status === 'DEAD') return 'exception'
  if (status === 'RUNNING') return 'warning'
  return ''
}
</script>

<style scoped lang="scss">
.index-jobs {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.job-row {
  &__meta {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 4px;
    font-size: 11px;
  }

  &__spacer {
    flex: 1;
  }

  &__error {
    margin-top: 4px;
    font-size: 11px;
    color: var(--ecom-danger);
  }
}
</style>
