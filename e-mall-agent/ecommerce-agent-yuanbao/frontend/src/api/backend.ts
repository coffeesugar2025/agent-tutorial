/**
 * 双后端切换（前端共用一套业务代码）。
 * VITE_BACKEND=python → /api/py/* → FastAPI；java → /api/java/* → Spring Boot。
 * nginx 把两条路径分别反代到 backend-python:8000 / backend-java:8080。
 */
export type BackendKind = 'python' | 'java'

const VITE_BACKEND = (import.meta.env?.VITE_BACKEND as BackendKind) || 'python'
const VITE_API_BASE = (import.meta.env?.VITE_API_BASE as string) || '/api'

export const backend: BackendKind = VITE_BACKEND === 'java' ? 'java' : 'python'

export function apiBase(): string {
  return VITE_BACKEND === 'java' ? `${VITE_API_BASE}/java` : `${VITE_API_BASE}/py`
}

export function apiUrl(path: string): string {
  const p = path.startsWith('/') ? path : `/${path}`
  return `${apiBase()}${p}`
}

/** 契约探测：两端都实现 /v3/capabilities，用来在界面上显示当前生效后端。 */
export async function detectBackend(): Promise<{ backend: string; chapters?: number; framework?: string }> {
  const res = await fetch(apiUrl('/v3/capabilities'))
  if (!res.ok) return { backend }
  const data = await res.json()
  return {
    backend: data.backend || backend,
    chapters: data.chapters,
    framework: data.framework || (backend === 'java' ? 'langchain4j 1.24.0' : 'LangChain 1.5.2'),
  }
}

export const BACKEND_LABEL: Record<BackendKind, string> = {
  python: 'Python · LangChain 1.5 / FastAPI',
  java: 'Java · LangChain4j 1.24 / Spring Boot',
}
