/** 后端 HTTP / SSE 客户端。前端只依赖 /api 前缀，由 Vite 代理转发。 */

import type { AgentEvent, HealthInfo, IntentInfo, ToolInfo } from '../types'
import { parseSSEBlock, splitSSEBuffer } from './sse'

const BASE = '/api'

async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, { signal })
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`)
  return (await resp.json()) as T
}

export function getHealth(): Promise<HealthInfo> {
  return getJSON<HealthInfo>('/health')
}

export function getTools(): Promise<ToolInfo[]> {
  return getJSON<ToolInfo[]>('/v1/tools')
}

export function detectIntent(message: string, threadId = 'intent'): Promise<IntentInfo> {
  return fetch(`${BASE}/v1/intent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, thread_id: threadId, user_id: 'u_1001' }),
  }).then(async (resp) => {
    if (!resp.ok) throw new Error(`intent -> HTTP ${resp.status}`)
    return (await resp.json()) as IntentInfo
  })
}

export interface ChatPayload {
  message: string
  thread_id: string
  user_id: string
}

/**
 * POST + SSE：EventSource 只支持 GET，所以用 fetch 读取 ReadableStream。
 * onEvent 会在每个完整事件块到达时同步回调；signal 用于「停止生成」。
 */
export async function streamChat(
  payload: ChatPayload,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(`${BASE}/v1/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!resp.ok || !resp.body) throw new Error(`chat -> HTTP ${resp.status}`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const consume = (chunk: string) => {
    buffer += chunk
    const { blocks, rest } = splitSSEBuffer(buffer)
    buffer = rest
    for (const block of blocks) {
      const parsed = parseSSEBlock(block)
      if (parsed) onEvent(parsed)
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    consume(decoder.decode(value, { stream: true }))
  }
  const tail = decoder.decode()
  if (tail) consume(tail)
  if (buffer.trim()) {
    const parsed = parseSSEBlock(`${buffer}\n`)
    if (parsed) onEvent(parsed)
  }
}
