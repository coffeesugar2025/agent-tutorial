/**
 * localStorage 封装：所有读写都做异常保护（隐私模式 / 配额满 / SSR）。
 * token 与用户信息按后端基地址隔离，切换后两套后端互不影响。
 */
import type { BackendId, UserVO } from '@/types'

const TOKEN_PREFIX = 'ecom.token::'
const USER_PREFIX = 'ecom.user::'
const BACKEND_ID_KEY = 'ecom.api.backend'
const BACKEND_BASE_KEY = 'ecom.api.base'
const SIDEBAR_KEY = 'ecom.ui.sidebar-collapsed'

function storage(): Storage | null {
  try {
    if (typeof window === 'undefined' || !window.localStorage) return null
    return window.localStorage
  } catch {
    return null
  }
}

export function readRaw(key: string): string | null {
  try {
    return storage()?.getItem(key) ?? null
  } catch {
    return null
  }
}

export function writeRaw(key: string, value: string): void {
  try {
    storage()?.setItem(key, value)
  } catch {
    /* 忽略写入失败 */
  }
}

export function removeRaw(key: string): void {
  try {
    storage()?.removeItem(key)
  } catch {
    /* 忽略删除失败 */
  }
}

function readJson<T>(key: string): T | null {
  const raw = readRaw(key)
  if (!raw) return null
  try {
    return JSON.parse(raw) as T
  } catch {
    return null
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    writeRaw(key, JSON.stringify(value))
  } catch {
    /* 忽略序列化失败 */
  }
}

/* ---------------- token / 用户 ---------------- */

export function readToken(base: string): string | null {
  return readRaw(`${TOKEN_PREFIX}${base}`)
}

export function writeToken(base: string, token: string): void {
  writeRaw(`${TOKEN_PREFIX}${base}`, token)
}

export function clearToken(base: string): void {
  removeRaw(`${TOKEN_PREFIX}${base}`)
}

export function readUser(base: string): UserVO | null {
  return readJson<UserVO>(`${USER_PREFIX}${base}`)
}

export function writeUser(base: string, user: UserVO): void {
  writeJson(`${USER_PREFIX}${base}`, user)
}

export function clearUser(base: string): void {
  removeRaw(`${USER_PREFIX}${base}`)
}

/* ---------------- 后端选择 ---------------- */

export function readBackendId(): BackendId | null {
  const value = readRaw(BACKEND_ID_KEY)
  return value === 'python' || value === 'java' || value === 'custom' ? value : null
}

export function writeBackendId(id: BackendId): void {
  writeRaw(BACKEND_ID_KEY, id)
}

export function readBackendBase(): string | null {
  return readRaw(BACKEND_BASE_KEY)
}

export function writeBackendBase(base: string): void {
  writeRaw(BACKEND_BASE_KEY, base)
}

/* ---------------- UI 偏好 ---------------- */

export function readSidebarCollapsed(): boolean {
  return readRaw(SIDEBAR_KEY) === '1'
}

export function writeSidebarCollapsed(collapsed: boolean): void {
  writeRaw(SIDEBAR_KEY, collapsed ? '1' : '0')
}
