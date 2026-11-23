<template>
  <div class="page">
    <PageHeader title="知识库" description="上传文档建立索引，查看异步索引进度，并做混合检索调试">
      <el-button size="small" :loading="docsLoading" @click="loadDocuments()">刷新</el-button>
    </PageHeader>

    <el-tabs v-model="activeTab">
      <el-tab-pane label="文档管理" name="documents">
        <div class="knowledge-grid">
          <div class="panel">
            <div class="panel__header">
              <span class="panel__title">上传文档</span>
              <span class="panel__subtitle">写入 Milvus 由异步任务完成</span>
            </div>
            <DocumentUploader @uploaded="onUploaded" />
          </div>

          <div v-if="jobs.length" class="panel">
            <IndexJobPanel :jobs="jobs" />
          </div>
        </div>

        <div class="panel panel--flush knowledge-docs">
          <div class="panel__header knowledge-docs__head">
            <span class="panel__title">文档列表</span>
            <el-select v-model="docTypeFilter" clearable placeholder="全部类型" style="width: 130px" @change="loadDocuments()">
              <el-option
                v-for="value in DOC_TYPES"
                :key="value"
                :label="metaOf(DOC_TYPE_META, value).label"
                :value="value"
              />
            </el-select>
            <el-select v-model="statusFilter" clearable placeholder="全部状态" style="width: 130px" @change="loadDocuments()">
              <el-option
                v-for="value in KNOWLEDGE_DOC_STATUSES"
                :key="value"
                :label="metaOf(DOC_STATUS_META, value).label"
                :value="value"
              />
            </el-select>
          </div>

          <DataState
            :loading="docsLoading"
            :error="docsError"
            :empty="!docsLoading && !docsError && documents.length === 0"
            empty-text="还没有文档"
            empty-description="上传 .md / .txt / .pdf / .docx 后可在此管理"
            @retry="loadDocuments()"
          >
            <el-table :data="documents" size="small">
              <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
              <el-table-column label="类型" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="metaOf(DOC_TYPE_META, row.docType).tone" effect="plain">
                    {{ metaOf(DOC_TYPE_META, row.docType).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="可见性" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="metaOf(VISIBILITY_META, row.visibility).tone" effect="plain">
                    {{ metaOf(VISIBILITY_META, row.visibility).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag size="small" :type="metaOf(DOC_STATUS_META, row.status).tone" effect="plain">
                    {{ metaOf(DOC_STATUS_META, row.status).label }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="version" label="版本" width="70" align="right" />
              <el-table-column prop="chunkCount" label="分片" width="80" align="right" />
              <el-table-column label="创建时间" width="170">
                <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="160" fixed="right">
                <template #default="{ row }">
                  <el-button size="small" text type="primary" @click="onReindex(row)">重建索引</el-button>
                  <el-button size="small" text type="danger" @click="onDelete(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </DataState>
        </div>
      </el-tab-pane>

      <el-tab-pane label="检索调试" name="retrieval">
        <div class="panel">
          <div class="panel__header">
            <span class="panel__title">检索调试</span>
            <span class="panel__subtitle">对比 dense / sparse / rerank 三路分数</span>
          </div>
          <RetrievalDebugPanel />
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { deleteDocument, getIndexJob, listDocuments, reindexDocument } from '@/api/knowledge'
import {
  DOC_TYPES,
  KNOWLEDGE_DOC_STATUSES,
  type DocType,
  type DocumentUploadResult,
  type IndexJobVO,
  type KnowledgeDocStatus,
  type KnowledgeDocumentVO,
} from '@/types'
import { errorMessage } from '@/utils/guard'
import {
  formatDateTime,
  metaOf,
  DOC_STATUS_META,
  DOC_TYPE_META,
  VISIBILITY_META,
} from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import DocumentUploader from '@/components/knowledge/DocumentUploader.vue'
import IndexJobPanel from '@/components/knowledge/IndexJobPanel.vue'
import RetrievalDebugPanel from '@/components/knowledge/RetrievalDebugPanel.vue'

const POLL_INTERVAL = 3000
const TERMINAL_STATUSES = ['SUCCESS', 'FAILED', 'DEAD']

const activeTab = ref<'documents' | 'retrieval'>('documents')
const documents = ref<KnowledgeDocumentVO[]>([])
const docsLoading = ref(false)
const docsError = ref('')
const docTypeFilter = ref<DocType | ''>('')
const statusFilter = ref<KnowledgeDocStatus | ''>('')
const jobs = ref<IndexJobVO[]>([])

let timer: number | null = null

async function loadDocuments(silent = false): Promise<void> {
  if (!silent) docsLoading.value = true
  docsError.value = ''
  try {
    const list = await listDocuments({
      docType: docTypeFilter.value || undefined,
      status: statusFilter.value || undefined,
    })
    documents.value = Array.isArray(list) ? list : []
  } catch (err) {
    docsError.value = errorMessage(err, '文档列表加载失败')
    if (!silent) documents.value = []
  } finally {
    if (!silent) docsLoading.value = false
  }
}

function upsertJob(job: IndexJobVO): void {
  const index = jobs.value.findIndex((item) => item.id === job.id)
  if (index >= 0) jobs.value[index] = { ...jobs.value[index], ...job }
  else jobs.value.push(job)
}

function trackJob(jobId: number, documentId = 0): void {
  upsertJob({ id: jobId, documentId, jobType: 'INDEX', status: 'QUEUED', progress: 0 })
  ensurePolling()
}

async function pollJobs(): Promise<void> {
  const pending = jobs.value.filter((job) => !TERMINAL_STATUSES.includes(job.status))
  if (pending.length === 0) {
    stopPolling()
    return
  }
  await Promise.all(
    pending.map(async (job) => {
      try {
        const data = await getIndexJob(job.id)
        const previous = job.status
        upsertJob({ ...job, ...data })
        if (data.status === 'SUCCESS' && previous !== 'SUCCESS') {
          ElMessage.success(`索引任务 #${job.id} 已完成`)
          void loadDocuments(true)
        }
        if ((data.status === 'FAILED' || data.status === 'DEAD') && previous !== data.status) {
          ElMessage.error(`索引任务 #${job.id} 失败：${data.error || '未知原因'}`)
        }
      } catch {
        /* 轮询失败保持原状态，下个周期重试 */
      }
    }),
  )
}

function ensurePolling(): void {
  if (timer !== null) return
  timer = window.setInterval(() => void pollJobs(), POLL_INTERVAL)
  void pollJobs()
}

function stopPolling(): void {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

function onUploaded(result: DocumentUploadResult): void {
  trackJob(result.jobId, result.documentId)
  void loadDocuments(true)
}

async function onReindex(document: KnowledgeDocumentVO): Promise<void> {
  try {
    const result = await reindexDocument(document.id)
    trackJob(result.jobId, document.id)
    ElMessage.success(`已提交重建索引任务 #${result.jobId}`)
    void loadDocuments(true)
  } catch (err) {
    ElMessage.error(errorMessage(err, '重建索引失败'))
  }
}

async function onDelete(document: KnowledgeDocumentVO): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除文档「${document.title}」？将软删除并异步清理向量。`, '删除文档', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  try {
    const result = await deleteDocument(document.id)
    if (result?.jobId) trackJob(result.jobId, document.id)
    ElMessage.success('已删除，向量清理任务已提交')
    void loadDocuments(true)
  } catch (err) {
    ElMessage.error(errorMessage(err, '删除失败'))
  }
}

onMounted(() => {
  void loadDocuments()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped lang="scss">
.knowledge-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(320px, 1fr);
  gap: 16px;
  margin-bottom: 16px;
}

.knowledge-docs {
  &__head {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 12px 16px;
    margin-bottom: 0;
    border-bottom: 1px solid var(--ecom-border);
  }
}

@media (max-width: 1000px) {
  .knowledge-grid {
    grid-template-columns: 1fr;
  }
}
</style>
