import { beforeEach, describe, expect, it, vi } from 'vitest'
import { chatStream, login } from '../src/api/client'
import type { ChatEvent } from '../src/types'

describe('api client', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('login posts credentials to /api/auth/login and stores the token', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        token: 'test-token',
        user_id: 'U001',
        role: 'customer',
        permissions: ['chat:use'],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await login('张三', '123456')

    expect(result.token).toBe('test-token')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/auth/login')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ username: '张三', password: '123456' })
    expect(localStorage.getItem('ecom_token')).toBe('test-token')
  })

  it('chatStream parses SSE data frames into event callbacks', async () => {
    const sse = [
      'data: {"event":"node","node":"context"}\n\n',
      'data: {"event":"route","data":"shopping"}\n\n',
      'data: {"event":"token","data":"你好"}\n\n',
      'data: {"event":"done","data":"你好"}\n\n',
    ].join('')

    const chunks = [sse.slice(0, 31), sse.slice(31, 63), sse.slice(63)]
    let cursor = 0
    const body = {
      getReader() {
        return {
          async read() {
            if (cursor < chunks.length) {
              const value = new TextEncoder().encode(chunks[cursor])
              cursor += 1
              return { done: false, value }
            }
            return { done: true }
          },
          releaseLock() { /* no-op for test double */ },
        }
      },
    }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, body })
    vi.stubGlobal('fetch', fetchMock)

    const events: ChatEvent[] = []
    await chatStream('推荐耳机', 'thread-1', (event) => events.push(event))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/chat/stream')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ message: '推荐耳机', thread_id: 'thread-1' })
    expect(events.map((event) => event.event)).toEqual(['node', 'route', 'token', 'done'])
    expect(events[0]).toEqual({ event: 'node', node: 'context' })
    expect(events[1]).toEqual({ event: 'route', data: 'shopping' })
    expect(events[2]).toEqual({ event: 'token', data: '你好' })
    expect(events[3]).toEqual({ event: 'done', data: '你好' })
  })
})
