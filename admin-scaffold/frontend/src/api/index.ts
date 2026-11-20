import { http } from './request'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  size: number
}

export interface Profile {
  id: number
  username: string
  nickname: string
  is_superuser: boolean
  roles: string[]
  permissions: string[]
}

export interface Menu {
  path: string
  title: string
  icon: string
  perm: string
}

export interface UserItem {
  id: number
  username: string
  nickname: string
  email: string
  phone: string
  is_active: boolean
  is_superuser: boolean
  created_at: string
  roles: string[]
  role_ids: number[]
}

export interface RoleItem {
  id: number
  code: string
  name: string
  description: string
  is_active: boolean
  created_at: string
  permission_ids: number[]
}

export interface PermissionItem {
  id: number
  code: string
  name: string
  module: string
  kind: string
  sort: number
  created_at: string
}

export interface PermGroup {
  module: string
  children: { id: number; code: string; name: string; kind: string }[]
}

export interface AuditItem {
  ts: string
  username: string
  action: string
  resource: string
  detail: string
  ip: string
}

export interface HealthState {
  mysql: boolean
  redis: boolean
  rabbitmq: boolean
  kafka: boolean
  elasticsearch: boolean
}

// 认证
export const loginApi = (data: { username: string; password: string }) =>
  http.post<{ access_token: string; refresh_token: string; expires_in: number }>('/auth/login', data)
export const getMe = () => http.get<Profile>('/auth/me')
export const getMenus = () => http.get<Menu[]>('/auth/menus')
export const logoutApi = () => http.post<null>('/auth/logout')

// 用户
export const getUsers = (params: { page: number; size: number; keyword?: string }) =>
  http.get<Page<UserItem>>('/users', params)
export const createUser = (data: object) => http.post<UserItem>('/users', data)
export const updateUser = (id: number, data: object) => http.put<UserItem>(`/users/${id}`, data)
export const deleteUser = (id: number) => http.delete<null>(`/users/${id}`)
export const resetPassword = (id: number, password: string) =>
  http.patch<null>(`/users/${id}/reset-password`, { password })

// 角色
export const getRoles = (params: { page: number; size: number; keyword?: string }) =>
  http.get<Page<RoleItem>>('/roles', params)
export const getRoleOptions = () =>
  http.get<{ id: number; code: string; name: string }[]>('/roles/options')
export const createRole = (data: object) => http.post<RoleItem>('/roles', data)
export const updateRole = (id: number, data: object) => http.put<RoleItem>(`/roles/${id}`, data)
export const deleteRole = (id: number) => http.delete<null>(`/roles/${id}`)
export const assignPermissions = (id: number, permission_ids: number[]) =>
  http.put<RoleItem>(`/roles/${id}/permissions`, { permission_ids })

// 权限
export const getPermissions = (params: { page: number; size: number; keyword?: string; module?: string }) =>
  http.get<Page<PermissionItem>>('/permissions', params)
export const getPermissionTree = () => http.get<PermGroup[]>('/permissions/tree')
export const createPermission = (data: object) => http.post<PermissionItem>('/permissions', data)
export const updatePermission = (id: number, data: object) =>
  http.put<PermissionItem>(`/permissions/${id}`, data)
export const deletePermission = (id: number) => http.delete<null>(`/permissions/${id}`)

// 审计 / 运维
export const getAuditLogs = (params: { page: number; size: number; keyword?: string; action?: string }) =>
  http.get<Page<AuditItem>>('/audit-logs', params)
export const getHealth = () => http.get<HealthState>('/health')
