<template>
  <div class="uploader">
    <el-upload
      drag
      :auto-upload="false"
      :show-file-list="false"
      accept=".md,.txt,.pdf,.docx"
      :on-change="onFileChange"
      class="uploader__drop"
    >
      <div class="uploader__glyph">⬆</div>
      <div class="uploader__text">将文件拖到此处，或 <em>点击选择</em></div>
      <div class="uploader__hint">支持 .md / .txt / .pdf / .docx，单文件不超过 20MB</div>
    </el-upload>

    <div v-if="file" class="uploader__file">
      <span class="uploader__file-name ellipsis">{{ file.name }}</span>
      <span class="uploader__file-size">{{ formatFileSize(file.size) }}</span>
      <el-button size="small" text type="danger" @click="clearFile">移除</el-button>
    </div>

    <div class="uploader__form">
      <el-input v-model="form.title" placeholder="文档标题（可选，缺省取文件名）" style="width: 260px" />
      <el-select v-model="form.docType" style="width: 132px">
        <el-option
          v-for="value in DOC_TYPES"
          :key="value"
          :label="metaOf(DOC_TYPE_META, value).label"
          :value="value"
        />
      </el-select>
      <el-select v-model="form.visibility" style="width: 120px">
        <el-option
          v-for="value in VISIBILITIES"
          :key="value"
          :label="metaOf(VISIBILITY_META, value).label"
          :value="value"
        />
      </el-select>
      <el-button type="primary" :loading="submitting" :disabled="!file" @click="submit">
        上传并索引
      </el-button>
      <span class="uploader__status text-muted">索引为异步任务，提交后可查看进度</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage, type UploadFile } from 'element-plus'
import { uploadDocument } from '@/api/knowledge'
import { DOC_TYPES, VISIBILITIES, type DocType, type DocumentUploadResult, type Visibility } from '@/types'
import { errorMessage } from '@/utils/guard'
import { formatFileSize, metaOf, DOC_TYPE_META, VISIBILITY_META } from '@/utils/format'

const emit = defineEmits<{ uploaded: [result: DocumentUploadResult] }>()

const ACCEPT_EXTENSIONS = ['.md', '.txt', '.pdf', '.docx']
const MAX_SIZE = 20 * 1024 * 1024

const file = ref<File | null>(null)
const submitting = ref(false)
const form = reactive<{ title: string; docType: DocType; visibility: Visibility }>({
  title: '',
  docType: 'POLICY',
  visibility: 'PUBLIC',
})

function onFileChange(uploadFile: UploadFile): void {
  const raw = uploadFile.raw
  if (!raw) return
  const name = raw.name.toLowerCase()
  if (!ACCEPT_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    ElMessage.warning('仅支持 .md / .txt / .pdf / .docx 文件')
    return
  }
  if (raw.size > MAX_SIZE) {
    ElMessage.warning('文件不能超过 20MB')
    return
  }
  file.value = raw
  if (!form.title) form.title = raw.name.replace(/\.[^.]+$/, '')
}

function clearFile(): void {
  file.value = null
}

async function submit(): Promise<void> {
  if (!file.value || submitting.value) return
  submitting.value = true
  try {
    const result = await uploadDocument(file.value, {
      title: form.title.trim() || undefined,
      docType: form.docType,
      visibility: form.visibility,
    })
    ElMessage.success(`已提交索引任务（job #${result.jobId}）`)
    emit('uploaded', result)
    file.value = null
    form.title = ''
  } catch (err) {
    ElMessage.error(errorMessage(err, '上传失败'))
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped lang="scss">
.uploader {
  &__drop {
    :deep(.el-upload-dragger) {
      padding: 18px 12px;
      border-radius: 10px;
    }
  }

  &__glyph {
    font-size: 22px;
    color: var(--ecom-primary);
  }

  &__text {
    margin-top: 4px;
    font-size: 13px;
    color: var(--ecom-text-regular);

    em {
      font-style: normal;
      color: var(--ecom-primary);
    }
  }

  &__hint {
    margin-top: 4px;
    font-size: 11px;
    color: var(--ecom-text-placeholder);
  }

  &__file {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 10px;
    margin-top: 8px;
    font-size: 12px;
    background: #f1f5f9;
    border-radius: 6px;
  }

  &__file-name {
    flex: 1;
    min-width: 0;
  }

  &__file-size {
    color: var(--ecom-text-secondary);
    flex-shrink: 0;
  }

  &__form {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    margin-top: 12px;
  }

  &__status {
    font-size: 11px;
  }
}
</style>
