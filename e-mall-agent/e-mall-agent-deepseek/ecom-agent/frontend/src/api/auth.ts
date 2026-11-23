import type { LoginRequest, LoginResult, UserVO } from '@/types'
import { get, post } from './http'

export function login(payload: LoginRequest): Promise<LoginResult> {
  return post<LoginResult>('/auth/login', payload)
}

export function me(config?: { silent?: boolean }): Promise<UserVO> {
  return get<UserVO>('/auth/me', undefined, { silent: config?.silent })
}
