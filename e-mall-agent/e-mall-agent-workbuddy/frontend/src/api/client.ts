import type {
  AuditEntry,
  ChatEvent,
  ChatResult,
  ContextPreview,
  EvalReport,
  FulfillmentResult,
  GraphBundle,
  HybridResult,
  LoginResult,
  MemoryResult,
  MetricsSnapshot,
  Order,
  PlanResult,
  Product,
  RagDoc,
  SandboxResult,
  Text2SQLResult,
  TraceEvent,
  User,
} from '../types'

// ---------- backend engine configuration ----------
export const TOKEN_KEY = 'ecom_token'
export const BACKEND_KEY = 'ecom_backend'
export const API_BASE_KEY = 'ecom_api_base_url'
export const DEFAULT_API_BASE_URL = 'http://localhost:8000'
export const DEFAULT_JAVA_API_URL = 'http://localhost:8080'

export type BackendKey = 'python' | 'java'

export interface BackendPreset {
  key: BackendKey
  label: string
  url: string
}

export const BACKEND_PRESETS: BackendPreset[] = [
  {
    key: 'python',
    label: 'Python · LangChain 1.5',
    url: import.meta.env.VITE_PYTHON_API_URL || DEFAULT_API_BASE_URL,
  },
  {
    key: 'java',
    label: 'Java · LangChain4j',
    url: import.meta.env.VITE_JAVA_API_URL || DEFAULT_JAVA_API_URL,
  },
]

function runtimeApiBaseUrl(): string | undefined {
  if (typeof window === 'undefined') return undefined
  const configured = window.__APP_CONFIG__?.API_BASE_URL
  return configured && configured.trim() ? configured.trim() : undefined
}

/** Resolve the active base URL: runtime config > Vite env > localStorage > default. */
export function getApiBaseUrl(): string {
  const envBase = import.meta.env.VITE_API_BASE_URL
  const envUrl = envBase && envBase.trim() ? envBase.trim() : undefined
  const storedUrl = localStorage.getItem(API_BASE_KEY) || undefined
  return runtimeApiBaseUrl() ?? envUrl ?? storedUrl ?? DEFAULT_API_BASE_URL
}

/** Persist a manual base URL override (used by localStorage-based switching). */
export function setApiBaseUrl(url: string): void {
  localStorage.setItem(API_BASE_KEY, url.trim())
}

export function getBackendKey(): BackendKey {
  return localStorage.getItem(BACKEND_KEY) === 'java' ? 'java' : 'python'
}

/** Pick a preset and persist both the key and its URL. */
export function setBackendKey(key: BackendKey): void {
  localStorage.setItem(BACKEND_KEY, key)
  localStorage.setItem(API_BASE_KEY, getBackendPreset(key).url)
}

export function getBackendPreset(key?: BackendKey): BackendPreset {
  const target = key ?? getBackendKey()
  return BACKEND_PRESETS.find((preset) => preset.key === target) ?? BACKEND_PRESETS[0]
}

/** Clear all backend overrides so resolution falls back to env/default. */
export function resetApiBaseUrl(): void {
  localStorage.removeItem(API_BASE_KEY)
  localStorage.removeItem(BACKEND_KEY)
}

/**
 * Build an API URL from the resolved base.
 * The built-in localhost default stays a same-origin `/api` path so the
 * Vite/nginx proxy handles routing; explicit bases become absolute URLs.
 */
export function apiUrl(path: string): string {
  const base = getApiBaseUrl().replace(/\/+$/, '')
  const suffix = path.startsWith('/') ? path : `/${path}`
  if (!base || base === DEFAULT_API_BASE_URL) return `/api${suffix}`
  return `${base}/api${suffix}`
}

/** GET /api/health on the currently selected backend. */
export async function probeHealth(): Promise<boolean> {
  try {
    const response = await fetch(apiUrl('/health'), { method: 'GET' })
    return response.ok
  } catch {
    return false
  }
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function readError(response: Response): Promise<string> {
  let detail = ''
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') detail = body.detail
    else if (Array.isArray(body.detail)) {
      detail = body.detail
        .map((item: unknown) => {
          if (item && typeof item === 'object' && 'msg' in item) {
            return String((item as { msg: unknown }).msg)
          }
          return String(item)
        })
        .join('; ')
    }
  } catch {
    try {
      detail = await response.text()
    } catch {
      detail = ''
    }
  }
  return detail || `请求失败 (${response.status} ${response.statusText})`
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders(), ...(options.headers as Record<string, string> | undefined) }
  const init: RequestInit = { ...options, headers }
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json'
  }
  const response = await fetch(apiUrl(path), init)
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  if (response.status === 204) {
    return undefined as T
  }
  return (await response.json()) as T
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) })
}

export async function login(username: string, password: string): Promise<LoginResult> {
  const result = await post<LoginResult>('/auth/login', { username, password })
  setToken(result.token)
  return result
}

export function me(): Promise<User> {
  return request<User>('/auth/me')
}

export function chat(message: string, threadId: string = 'default'): Promise<ChatResult> {
  return post<ChatResult>('/chat', { message, thread_id: threadId })
}

export async function chatStream(
  message: string,
  threadId: string,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await fetch(apiUrl('/chat/stream'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ message, thread_id: threadId }),
  })
  if (!response.ok) {
    throw new Error(await readError(response))
  }
  if (!response.body) {
    throw new Error('服务端未返回流式响应体')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const handleBlock = (block: string): void => {
    const dataLines = block
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trimStart())
    if (dataLines.length === 0) return
    const payload = dataLines.join('\n').trim()
    if (!payload) return
    try {
      onEvent(JSON.parse(payload) as ChatEvent)
    } catch {
      // Ignore malformed or non-JSON keep-alive frames.
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        handleBlock(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) handleBlock(buffer)
  } finally {
    reader.releaseLock()
  }
}

export function listProducts(query: string = ''): Promise<Product[]> {
  const suffix = query ? `?query=${encodeURIComponent(query)}` : ''
  return request<Product[]>(`/products${suffix}`)
}

export function createOrder(items: Array<{ product_id: string; quantity: number }>): Promise<Order> {
  return post<Order>('/orders', { items })
}

export function listOrders(): Promise<Order[]> {
  return request<Order[]>('/orders')
}

export function refund(orderId: string, reason: string): Promise<{ order_id: string; status: string }> {
  return post<{ order_id: string; status: string }>(`/orders/${encodeURIComponent(orderId)}/refund`, { reason })
}

export function graphs(): Promise<GraphBundle> {
  return request<GraphBundle>('/graphs')
}

export function traces(limit: number = 50): Promise<TraceEvent[]> {
  return request<TraceEvent[]>(`/traces?limit=${limit}`)
}

export function audit(limit: number = 50): Promise<AuditEntry[]> {
  return request<AuditEntry[]>(`/audit?limit=${limit}`)
}

export function contextPreview(message: string): Promise<ContextPreview> {
  return request<ContextPreview>(`/context/preview?message=${encodeURIComponent(message)}`)
}

export function ragSearch(q: string): Promise<RagDoc[]> {
  return request<RagDoc[]>(`/rag/search?q=${encodeURIComponent(q)}`)
}

export function runFulfillment(orderId: string, threadId?: string): Promise<FulfillmentResult> {
  return post<FulfillmentResult>('/workflows/fulfillment/run', {
    order_id: orderId,
    ...(threadId ? { thread_id: threadId } : {}),
  })
}

export function resumeFulfillment(threadId: string, approved: boolean): Promise<FulfillmentResult> {
  return post<FulfillmentResult>('/workflows/fulfillment/resume', {
    thread_id: threadId,
    approved,
  })
}

// ---------- extended capabilities ----------
export function planGoal(goal: string, mode: 'react' | 'plan_solve'): Promise<PlanResult> {
  return post<PlanResult>('/capabilities/plan', { goal, mode })
}

export function hybridSearch(query: string, topK = 5, mode = 'hybrid'): Promise<HybridResult> {
  return post<HybridResult>('/capabilities/rag/hybrid', { query, top_k: topK, mode })
}

export function memoryRecall(threadId = 'default', query = ''): Promise<MemoryResult> {
  return request<MemoryResult>(
    `/capabilities/memory?thread_id=${encodeURIComponent(threadId)}&query=${encodeURIComponent(query)}`,
  )
}

export function sandboxRun(code: string, mode: 'plain' | 'code_mode'): Promise<SandboxResult> {
  return post<SandboxResult>('/capabilities/sandbox', { code, mode })
}

export function text2sql(question: string): Promise<Text2SQLResult> {
  return post<Text2SQLResult>('/capabilities/rag/text2sql', { question })
}

export function metricsSnapshot(): Promise<MetricsSnapshot> {
  return request<MetricsSnapshot>('/capabilities/metrics')
}

export function evaluateCases(cases: Array<Record<string, unknown>>): Promise<{ report: EvalReport }> {
  return post<{ report: EvalReport }>('/capabilities/eval', { cases, runner: 'echo' })
}
