import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { hybridSearch, planGoal, sandboxRun, TOKEN_KEY } from '../src/api/client'

describe('capability API client', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    localStorage.setItem(TOKEN_KEY, 'test-token')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    localStorage.clear()
  })

  it('planGoal posts goal and mode to /api/capabilities/plan', async () => {
    const fake = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ answer: 'done', trace: [], terminated_reason: '', mode: 'react' }),
    })
    vi.stubGlobal('fetch', fake)

    const result = await planGoal('查询P001库存', 'react')

    expect(result.answer).toBe('done')
    const [url, init] = fake.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/capabilities/plan')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ goal: '查询P001库存', mode: 'react' })
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer test-token')
  })

  it('hybridSearch parses RRF source details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        count: 1,
        results: [{
          id: 'seed-0', content: '退款政策', score: 0.016, rank: 1,
          metadata: { source: 'policy' },
          sources: {
            bm25: { channel: 'bm25', rank: 1, raw_score: 2.5, contribution: 0.016 },
          },
        }],
        context: '退款政策',
      }),
    }))

    const result = await hybridSearch('退款政策', 3, 'bm25')

    expect(result.count).toBe(1)
    expect(result.results[0].sources.bm25.raw_score).toBe(2.5)
  })

  it('sandboxRun returns execution result', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ ok: true, value: 42, stdout: '42\n', error: '', duration_ms: 0.4 }),
    }))

    const result = await sandboxRun('6*7', 'plain')

    expect(result.ok).toBe(true)
    expect(result.value).toBe(42)
  })
})
