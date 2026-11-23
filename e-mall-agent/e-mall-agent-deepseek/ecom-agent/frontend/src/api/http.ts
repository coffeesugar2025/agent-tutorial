import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import {
  ERROR_CODES,
  type ApiEnvelope,
  type BackendId,
  type BackendOption,
  type BackendSelection,
} from '@/types'
import { errorMessage, isRecord } from '@/utils/guard'
import {
  clearToken,
  readBackendBase,
  readBackendId,
  readToken,
  writeBackendBase,
  writeBackendId,
  writeToken,
} from '@/utils/storage'

export const FALLBACK_API_BASE = '/api'

function normalizeBase(base: string): string {
  const trimmed = base.trim()
  return trimmed.length > 1 ? trimmed.replace(/\/+$/, '') : trimmed
}

/** 两套后端预设，可由 .env 覆盖（VITE_BACKEND_PYTHON / VITE_BACKEND_JAVA） */
export const BACKEND_OPTIONS: BackendOption[] = [
  {
    id: 'python',
    label: 'Python · FastAPI',
    base: normalizeBase(import.meta.env.VITE_BACKEND_PYTHON || 'http://localhost:8000/api/v1'),
  },
  {
    id: 'java',
    label: 'Java · Spring Boot',
    base: normalizeBase(import.meta.env.VITE_BACKEND_JAVA || 'http://localhost:8080/api/v1'),
  },
]

/** 当前基地址：localStorage 优先，其次 VITE_API_BASE，最后 /api */
export function getApiBase(): string {
  return readBackendBase() || normalizeBase(import.meta.env.VITE_API_BASE || FALLBACK_API_BASE)
}

export function getBackendSelection(): BackendSelection {
  const base = getApiBase()
  const preset = BACKEND_OPTIONS.find((option) => option.base === base)
  const stored = readBackendId()
  const id: BackendId = stored === 'custom' ? 'custom' : preset?.id ?? stored ?? 'custom'
  return { id, base }
}

/** 切换后端：写入 localStorage，之后的请求由拦截器即时生效 */
export function setBackendSelection(id: BackendId, base?: string): BackendSelection {
  const preset = BACKEND_OPTIONS.find((option) => option.id === id)
  const resolved = normalizeBase(base || preset?.base || getApiBase())
  writeBackendId(id)
  writeBackendBase(resolved)
  return { id, base: resolved }
}

export function getBackendOption(id: BackendId): BackendOption | undefined {
  return BACKEND_OPTIONS.find((option) => option.id === id)
}

export function apiUrl(path: string): string {
  const base = getApiBase()
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

/* ------------------------------ token ------------------------------ */

export function getAuthToken(): string {
  return readToken(getApiBase()) ?? ''
}

export function setAuthToken(token: string): void {
  const base = getApiBase()
  if (!token) {
    clearToken(base)
    return
  }
  // token 按后端基地址隔离存储，切后端不会串号
  writeToken(base, token)
}

export function clearAuthToken(): void {
  clearToken(getApiBase())
}

/* ------------------------------ 错误 ------------------------------ */

export interface ApiErrorInit {
  code?: number
  message: string
  traceId?: string
  httpStatus?: number
  silent?: boolean
}

export class ApiError extends Error {
  readonly code: number
  readonly traceId?: string
  readonly httpStatus?: number
  readonly silent: boolean

  constructor(init: ApiErrorInit) {
    super(init.message)
    this.name = 'ApiError'
    this.code = init.code ?? -1
    this.traceId = init.traceId
    this.httpStatus = init.httpStatus
    this.silent = init.silent ?? false
  }
}

export function isEnvelope(value: unknown): value is ApiEnvelope<unknown> {
  return isRecord(value) && typeof value.code === 'number' && 'data' in value
}

/** 统一信封解包：code !== 0 一律抛 ApiError */
export function unwrapEnvelope<T>(envelope: unknown, httpStatus?: number): T {
  if (!isEnvelope(envelope)) {
    throw new ApiError({ code: -1, message: '响应格式不符合契约（缺少 code/data）', httpStatus })
  }
  if (envelope.code !== ERROR_CODES.OK) {
    throw new ApiError({
      code: envelope.code,
      message: envelope.message || '请求失败',
      traceId: envelope.traceId,
      httpStatus,
    })
  }
  return envelope.data as T
}

function httpMessage(status?: number): string {
  switch (status) {
    case 400:
      return '参数校验失败'
    case 401:
      return '登录已失效，请重新登录'
    case 403:
      return '没有权限执行该操作'
    case 404:
      return '资源不存在'
    case 409:
      return '状态冲突，请刷新后重试'
    case 429:
      return '请求过于频繁，请稍后再试'
    case 503:
      return '依赖服务降级中'
    case 504:
      return '上游超时'
    default:
      return `请求失败${status ? `（HTTP ${status}）` : ''}`
  }
}

function normalizeError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (axios.isAxiosError(error)) {
    const silent = error.config?.silent === true
    const status = error.response?.status
    const body: unknown = error.response?.data
    if (isEnvelope(body)) {
      return new ApiError({
        code: body.code,
        message: body.message || httpMessage(status),
        traceId: body.traceId,
        httpStatus: status,
        silent,
      })
    }
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return new ApiError({ code: ERROR_CODES.UPSTREAM_TIMEOUT, message: '请求超时，请稍后重试', silent })
    }
    if (!error.response) {
      return new ApiError({ code: -1, message: '网络异常，无法连接后端服务', silent })
    }
    return new ApiError({ code: -1, message: httpMessage(status), httpStatus: status, silent })
  }
  return new ApiError({ message: errorMessage(error) })
}

/* ------------------------------ 401 处理 ------------------------------ */

let unauthorizedHandler: (() => void) | null = null
let lastUnauthorizedAt = 0

export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler
}

function handleUnauthorized(): void {
  clearAuthToken()
  const now = Date.now()
  if (now - lastUnauthorizedAt > 2000) {
    lastUnauthorizedAt = now
    ElMessage.warning('登录已失效，请重新登录')
  }
  unauthorizedHandler?.()
}

/* ------------------------------ axios 实例 ------------------------------ */

const instance: AxiosInstance = axios.create({
  baseURL: getApiBase(),
  timeout: Number(import.meta.env.VITE_REQUEST_TIMEOUT) || 20000,
  headers: { 'Content-Type': 'application/json' },
})

instance.interceptors.request.use((config) => {
  // 动态基地址：切换后端后无需重建实例
  config.baseURL = getApiBase()
  const token = getAuthToken()
  if (token) config.headers.set('Authorization', `Bearer ${token}`)
  return config
})

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  try {
    const response = await instance.request<unknown>(config)
    return unwrapEnvelope<T>(response.data, response.status)
  } catch (error) {
    const apiError = normalizeError(error)
    if (apiError.code === ERROR_CODES.UNAUTHORIZED || apiError.httpStatus === 401) {
      handleUnauthorized()
    } else if (!apiError.silent) {
      ElMessage.error(apiError.message)
    }
    throw apiError
  }
}

export function get<T>(
  url: string,
  params?: Record<string, unknown>,
  config?: AxiosRequestConfig,
): Promise<T> {
  return request<T>({ ...config, url, method: 'GET', params: compactParams(params) })
}

export function post<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ ...config, url, method: 'POST', data })
}

export function put<T>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ ...config, url, method: 'PUT', data })
}

export function del<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
  return request<T>({ ...config, url, method: 'DELETE' })
}

/** 过滤 undefined / null / 空字符串，避免后端把 "undefined" 当参数 */
export function compactParams(params?: Record<string, unknown>): Record<string, unknown> | undefined {
  if (!params) return undefined
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    result[key] = value
  }
  return result
}

export default instance
