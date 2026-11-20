// 统一 API 封装：超时、错误归一化、中文提示。
// 开发环境由 Vite proxy 转发 /api → http://127.0.0.1:8000；生产由 FastAPI 同源托管。

const API_BASE = ''
const DEFAULT_TIMEOUT = 15000

export class ApiError extends Error {
  constructor(message, { status = 0, detail = '', kind = 'http' } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.kind = kind // http | network | timeout | invalid
  }
}

export const NETWORK_HINT = '请确认后端已启动（python app/backend/main.py，默认 8000 端口），或检查 /api 代理配置。'

async function request(path, { method = 'GET', body, timeout = DEFAULT_TIMEOUT, signal } = {}) {
  const controller = new AbortController()
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeout)
  const abortFromOutside = () => controller.abort()
  signal?.addEventListener('abort', abortFromOutside)

  try {
    let response
    try {
      response = await fetch(`${API_BASE}${path}`, {
        method,
        headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      })
    } catch (error) {
      if (timedOut) {
        throw new ApiError(`请求超时（${Math.round(timeout / 1000)} 秒）。${NETWORK_HINT}`, { kind: 'timeout' })
      }
      throw new ApiError(`无法连接到后端服务。${NETWORK_HINT}`, { kind: 'network', detail: String(error) })
    }

    const text = await response.text()
    let data = null
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        data = null
      }
    }

    if (!response.ok) {
      const detail = typeof data?.detail === 'string' ? data.detail : ''
      const message = detail || `请求失败（HTTP ${response.status}）`
      throw new ApiError(message, { status: response.status, detail, kind: 'http' })
    }
    if (data === null) {
      throw new ApiError('后端返回的不是合法 JSON，请检查接口实现。', { kind: 'invalid', status: response.status })
    }
    return data
  } finally {
    clearTimeout(timer)
    signal?.removeEventListener('abort', abortFromOutside)
  }
}

export const api = {
  health: () => request('/api/health', { timeout: 8000 }),
  getCourse: () => request('/api/course', { timeout: 12000 }),
  getDoc: (slug) => request(`/api/docs/${encodeURIComponent(slug)}`, { timeout: 15000 }),
  getScenarios: () => request('/api/scenarios', { timeout: 10000 }),
  chat: ({ sessionId, message, employeeId }) =>
    request('/api/chat', {
      method: 'POST',
      body: { session_id: sessionId, message, employee_id: employeeId },
      timeout: 40000,
    }),
  decideApproval: ({ approvalId, decision, comment, approver }) =>
    request(`/api/approvals/${encodeURIComponent(approvalId)}`, {
      method: 'POST',
      body: { decision, comment, approver },
      timeout: 30000,
    }),
  getSession: (sessionId) => request(`/api/sessions/${encodeURIComponent(sessionId)}`, { timeout: 10000 }),
  resetDemo: () => request('/api/demo/reset', { method: 'POST', body: {}, timeout: 15000 }),
  searchKb: (query, topK = 5) =>
    request(`/api/kb/search?q=${encodeURIComponent(query)}&top_k=${topK}`, { timeout: 12000 }),
  runEval: () => request('/api/eval/run', { method: 'POST', body: {}, timeout: 60000 }),
}

/** 生成前端会话 id，格式与契约一致：s_ + 随机串。 */
export function createSessionId() {
  const random = Math.random().toString(36).slice(2, 10)
  const stamp = Date.now().toString(36).slice(-4)
  return `s_${random}${stamp}`
}

/** 供页面展示的紧凑错误信息。 */
export function errorMessage(error) {
  if (error instanceof ApiError) return error.message
  if (error instanceof Error && error.message) return error.message
  return '发生未知错误，请重试。'
}
