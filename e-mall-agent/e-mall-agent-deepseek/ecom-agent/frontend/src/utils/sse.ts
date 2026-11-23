/**
 * SSE 客户端：EventSource 不支持 POST + Authorization，因此用 fetch + ReadableStream 手写解析。
 *
 * 协议见 docs/03-API契约.md：
 * - 十种事件：meta/agent/delta/tool_call/tool_result/citation/approval/usage/done/error
 * - `: ping` 心跳注释忽略；事件块以空行分隔，data 可为多行
 * - 断线不自动重试（对话重放会重复落库/重复计费），错误交给上层显式展示
 */
import { getApiBase, getAuthToken } from '@/api/http'
import type { ChatStreamRequest, ErrorEventData } from '@/types'
import { errorMessage, isAbortError, isRecord } from '@/utils/guard'
import {
  dispatchFrame,
  parseSseBlock,
  parseSseData,
  type SseFrame,
  type StreamCloseReason,
  type StreamHandlers,
} from '@/utils/sseParser'

export { parseSseBlock, dispatchFrame } from '@/utils/sseParser'
export type { SseFrame, StreamCloseReason, StreamHandlers } from '@/utils/sseParser'

async function readHttpError(response: Response): Promise<ErrorEventData> {
  let text = ''
  try {
    text = await response.text()
  } catch {
    /* 忽略读取失败 */
  }
  if (text) {
    const body = parseSseData(text)
    if (isRecord(body) && typeof body.code === 'number') {
      const message = typeof body.message === 'string' && body.message ? body.message : `请求失败（HTTP ${response.status}）`
      return { code: body.code, message }
    }
  }
  if (response.status === 401) return { code: 40100, message: '登录已失效，请重新登录' }
  return { code: -1, message: `对话接口返回 HTTP ${response.status}` }
}

/**
 * 发起流式对话。所有错误都通过 handlers.onError + onClose('error') 呈现，不抛异常。
 * 中断：传入 AbortSignal，abort 后 onClose('aborted')。
 */
export async function streamChat(
  payload: ChatStreamRequest,
  handlers: StreamHandlers = {},
  signal?: AbortSignal,
): Promise<void> {
  if (signal?.aborted) {
    handlers.onClose?.('aborted')
    return
  }

  const url = `${getApiBase().replace(/\/+$/, '')}/chat/stream`
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  }
  const token = getAuthToken()
  if (token) headers.Authorization = `Bearer ${token}`

  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal,
      cache: 'no-store',
    })
  } catch (error) {
    if (signal?.aborted || isAbortError(error)) {
      handlers.onClose?.('aborted')
      return
    }
    handlers.onError?.({
      code: -1,
      message: `无法连接对话服务（${url}），请确认后端已启动且地址正确`,
    })
    handlers.onClose?.('error')
    return
  }

  if (!response.ok) {
    handlers.onError?.(await readHttpError(response))
    handlers.onClose?.('error')
    return
  }
  if (!response.body) {
    handlers.onError?.({ code: -1, message: '当前浏览器不支持流式响应（response.body 为空）' })
    handlers.onClose?.('error')
    return
  }

  handlers.onOpen?.()

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let closeReason: StreamCloseReason = 'closed'
  let stopped = false

  /** 从缓冲区取出一个完整事件块（以空行结尾） */
  const takeBlock = (): string | null => {
    const match = /\r?\n\r?\n/.exec(buffer)
    if (!match || match.index === undefined) return null
    const block = buffer.slice(0, match.index)
    buffer = buffer.slice(match.index + match[0].length)
    return block
  }

  const drain = (): boolean => {
    let block: string | null
    while ((block = takeBlock()) !== null) {
      const frame: SseFrame | null = parseSseBlock(block)
      if (!frame) continue // 心跳 / 纯注释块
      const reason = dispatchFrame(frame, handlers)
      if (reason) {
        closeReason = reason
        return true
      }
    }
    return false
  }

  try {
    while (!stopped) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      stopped = drain()
    }
    if (!stopped) {
      // flush 解码器尾部 + 处理无结尾空行的最后一帧
      buffer += decoder.decode()
      if (buffer.trim()) {
        const frame = parseSseBlock(buffer)
        if (frame) {
          const reason = dispatchFrame(frame, handlers)
          if (reason) closeReason = reason
        }
      }
    }
  } catch (error) {
    if (signal?.aborted || isAbortError(error)) {
      closeReason = 'aborted'
    } else {
      handlers.onError?.({ code: -1, message: `流式连接中断：${errorMessage(error)}` })
      closeReason = 'error'
    }
  } finally {
    try {
      await reader.cancel()
    } catch {
      /* 连接已关闭 */
    }
  }

  handlers.onClose?.(closeReason)
}
