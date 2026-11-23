/**
 * 轻量类型守卫工具：处理 `unknown`（JSON 响应、SSE data）而不引入 any。
 */

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {}
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

export function pickString(source: unknown, key: string, fallback = ''): string {
  if (!isRecord(source)) return fallback
  const value = source[key]
  return typeof value === 'string' ? value : fallback
}

export function pickOptionalString(source: unknown, key: string): string | undefined {
  if (!isRecord(source)) return undefined
  const value = source[key]
  return typeof value === 'string' ? value : undefined
}

export function pickNumber(source: unknown, key: string, fallback = 0): number {
  if (!isRecord(source)) return fallback
  const value = source[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

export function pickBoolean(source: unknown, key: string, fallback = false): boolean {
  if (!isRecord(source)) return fallback
  const value = source[key]
  return typeof value === 'boolean' ? value : fallback
}

export function pickRecord(source: unknown, key: string): Record<string, unknown> {
  if (!isRecord(source)) return {}
  const value = source[key]
  return isRecord(value) ? value : {}
}

export function pickArray(source: unknown, key: string): unknown[] {
  if (!isRecord(source)) return []
  return asArray(source[key])
}

export function isAbortError(error: unknown): boolean {
  if (!isRecord(error)) return false
  return error.name === 'AbortError' || error.code === 'ERR_CANCELED' || error.code === 20
}

/** 把任意异常转成可展示的中文文案 */
export function errorMessage(error: unknown, fallback = '请求失败，请稍后重试'): string {
  if (typeof error === 'string' && error.trim()) return error
  if (error instanceof Error && error.message) return error.message
  if (isRecord(error)) {
    const message = error.message
    if (typeof message === 'string' && message) return message
  }
  return fallback
}

export function uid(prefix = 'id'): string {
  const globalCrypto = globalThis.crypto
  if (globalCrypto && typeof globalCrypto.randomUUID === 'function') {
    return `${prefix}-${globalCrypto.randomUUID()}`
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}
