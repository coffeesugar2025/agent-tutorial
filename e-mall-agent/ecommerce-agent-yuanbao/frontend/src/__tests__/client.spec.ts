import { afterEach, describe, expect, it, vi } from 'vitest'
import { streamChat } from '../api/client'
import type { AgentEvent } from '../types'

function sseResponse(chunks: string[], status = 200): Response {
  const encoder = new TextEncoder()
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
  return new Response(status === 200 ? body : null, { status })
}

const payload = { message: '找耳机', thread_id: 't1', user_id: 'u_1001' }

afterEach(() => vi.unstubAllGlobals())

describe('streamChat', () => {
  it('按分块到达顺序还原事件序列（含跨 chunk 的事件块）', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        'event: meta\ndata: {"thread_id":"t1"}\n\nevent: token\ndata: {"te',
        'xt":"你好"}\n\nevent: done\ndata: {"tool_calls":1}\n\n',
      ]),
    )
    vi.stubGlobal('fetch', fetchMock)

    const events: AgentEvent[] = []
    await streamChat(payload, (e) => events.push(e))

    expect(events.map((e) => e.event)).toEqual(['meta', 'token', 'done'])
    expect(events[1].data.text).toBe('你好')
    expect(fetchMock).toHaveBeenCalledOnce()
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/chat')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual(payload)
  })

  it('服务端非 200 时抛错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(sseResponse([], 502)))
    await expect(streamChat(payload, () => {})).rejects.toThrow('HTTP 502')
  })

  it('忽略非法块但保留合法事件', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      sseResponse([
        'event: bogus\ndata: {}\n\nevent: error\ndata: {"message":"boom"}\n\n',
      ]),
    ))
    const events: AgentEvent[] = []
    await streamChat(payload, (e) => events.push(e))
    expect(events).toHaveLength(1)
    expect(events[0].event).toBe('error')
  })
})
