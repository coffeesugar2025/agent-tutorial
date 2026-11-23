/** 通用信封、分页、后端切换与系统能力 */

export interface ApiEnvelope<T> {
  code: number
  message: string
  data: T
  traceId: string
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface PageQuery {
  page?: number
  size?: number
}

export const ERROR_CODES = {
  OK: 0,
  PARAM_INVALID: 40001,
  UNAUTHORIZED: 40100,
  FORBIDDEN: 40300,
  NOT_FOUND: 40400,
  CONFLICT: 40900,
  RATE_LIMITED: 42900,
  INTERNAL: 50000,
  DEGRADED: 50300,
  UPSTREAM_TIMEOUT: 50400,
} as const

export interface HealthVO {
  status: 'UP' | 'DEGRADED' | 'DOWN'
  components: Record<string, string>
}

export interface CapabilityFeatures {
  [key: string]: boolean
  mcp: boolean
  skills: boolean
  codeMode: boolean
  text2sql: boolean
  hybridRag: boolean
}

export interface CapabilitiesVO {
  backend: string
  version: string
  features: CapabilityFeatures
  llm: {
    primary: string
    fallbacks: string[]
  }
}

export type BackendId = 'python' | 'java' | 'custom'

export interface BackendOption {
  id: BackendId
  label: string
  base: string
}

export interface BackendSelection {
  id: BackendId
  base: string
}
