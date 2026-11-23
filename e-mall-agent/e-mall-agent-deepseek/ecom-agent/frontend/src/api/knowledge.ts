import type {
  DocType,
  DocumentUploadForm,
  DocumentUploadResult,
  IndexJobVO,
  KnowledgeDocumentVO,
  KnowledgeSearchRequest,
  KnowledgeSearchResult,
  ReindexResult,
} from '@/types'
import { compactParams, del, get, post } from './http'

export interface DocumentQuery {
  docType?: DocType
  status?: string
}

/** multipart 上传：由浏览器补 boundary，不要手动 JSON 化 */
export function uploadDocument(file: File, form: DocumentUploadForm): Promise<DocumentUploadResult> {
  const body = new FormData()
  body.append('file', file)
  if (form.title) body.append('title', form.title)
  body.append('docType', form.docType)
  body.append('visibility', form.visibility)
  return post<DocumentUploadResult>('/knowledge/documents', body, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 60000,
  })
}

export function listDocuments(query: DocumentQuery = {}): Promise<KnowledgeDocumentVO[]> {
  return get<KnowledgeDocumentVO[]>(
    '/knowledge/documents',
    compactParams({ docType: query.docType, status: query.status }),
  )
}

export function deleteDocument(documentId: number): Promise<ReindexResult> {
  return del<ReindexResult>(`/knowledge/documents/${documentId}`)
}

export function reindexDocument(documentId: number): Promise<ReindexResult> {
  return post<ReindexResult>(`/knowledge/documents/${documentId}/reindex`, {})
}

export function getIndexJob(jobId: number): Promise<IndexJobVO> {
  return get<IndexJobVO>(`/knowledge/jobs/${jobId}`, undefined, { silent: true })
}

export function searchKnowledge(payload: KnowledgeSearchRequest): Promise<KnowledgeSearchResult> {
  return post<KnowledgeSearchResult>('/knowledge/search', payload)
}
