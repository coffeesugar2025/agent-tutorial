import type {
  AuditEntry,
  ChatEvent,
  ChatResult,
  ContextPreview,
  FulfillmentResult,
  GraphBundle,
  LoginResult,
  Order,
  Product,
  RagDoc,
  TraceEvent,
  User,
} from '../types'

export const TOKEN_KEY = 'ecom_token'

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
  const response = await fetch(`/api${path}`, init)
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
  const response = await fetch('/api/chat/stream', {
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
