/** 知识库与检索调试 */

export const DOC_TYPES = ['POLICY', 'MANUAL', 'FAQ', 'PRODUCT_DOC'] as const
export type DocType = (typeof DOC_TYPES)[number]

export const VISIBILITIES = ['PUBLIC', 'INTERNAL', 'ADMIN'] as const
export type Visibility = (typeof VISIBILITIES)[number]

export const KNOWLEDGE_DOC_STATUSES = ['QUEUED', 'INDEXING', 'READY', 'FAILED', 'DELETING'] as const
export type KnowledgeDocStatus = (typeof KNOWLEDGE_DOC_STATUSES)[number]

export const INDEX_JOB_STATUSES = ['QUEUED', 'RUNNING', 'SUCCESS', 'FAILED', 'DEAD'] as const
export type IndexJobStatus = (typeof INDEX_JOB_STATUSES)[number]

export const INDEX_JOB_TYPES = ['INDEX', 'DELETE', 'REINDEX'] as const
export type IndexJobType = (typeof INDEX_JOB_TYPES)[number]

export const SEARCH_MODES = ['hybrid', 'dense', 'sparse'] as const
export type SearchMode = (typeof SEARCH_MODES)[number]

export interface KnowledgeDocumentVO {
  id: number
  title: string
  docType: DocType
  visibility: Visibility
  status: KnowledgeDocStatus
  version: number
  chunkCount: number
  createdAt: string
}

export interface DocumentUploadResult {
  documentId: number
  jobId: number
  status: string
}

export interface DocumentUploadForm {
  title?: string
  docType: DocType
  visibility: Visibility
}

export interface IndexJobVO {
  id: number
  documentId: number
  jobType: IndexJobType
  status: IndexJobStatus
  progress: number
  error?: string | null
}

export interface ReindexResult {
  jobId: number
}

export interface KnowledgeSearchRequest {
  query: string
  topK?: number
  docTypes?: DocType[]
  mode?: SearchMode
}

export interface KnowledgeSearchItem {
  chunkId: number
  documentId: number
  title: string
  content: string
  score: number
  denseScore?: number
  sparseScore?: number
  rerankScore?: number
  route: string
}

export interface KnowledgeSearchDebug {
  denseTopK: number
  sparseTopK: number
  rerankTopN: number
  latencyMs: number
}

export interface KnowledgeSearchResult {
  items: KnowledgeSearchItem[]
  debug: KnowledgeSearchDebug
}
