import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as authApi from '@/api/auth'
import { ApiError, clearAuthToken, getApiBase, getAuthToken, setAuthToken } from '@/api/http'
import type { LoginRequest, LoginResult, UserVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { clearUser, readUser, writeUser } from '@/utils/storage'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(getAuthToken())
  const user = ref<UserVO | null>(readUser(getApiBase()))
  const loading = ref(false)
  const error = ref('')

  const isLoggedIn = computed(() => Boolean(token.value))
  const displayName = computed(() => user.value?.displayName || user.value?.username || '未登录')
  const roles = computed<string[]>(() => user.value?.roles ?? [])
  const isAdmin = computed(() => roles.value.includes('ADMIN'))

  function clear(): void {
    token.value = ''
    user.value = null
    error.value = ''
    clearAuthToken()
    clearUser(getApiBase())
  }

  /** 从 localStorage 同步当前后端对应的登录态（切换后端时调用） */
  function refreshFromStorage(): void {
    token.value = getAuthToken()
    user.value = readUser(getApiBase())
  }

  async function login(payload: LoginRequest): Promise<boolean> {
    if (loading.value) return false
    loading.value = true
    error.value = ''
    try {
      const result: LoginResult = await authApi.login(payload)
      setAuthToken(result.token)
      token.value = result.token
      user.value = result.user
      writeUser(getApiBase(), result.user)
      return true
    } catch (err) {
      error.value = errorMessage(err, '登录失败')
      return false
    } finally {
      loading.value = false
    }
  }

  async function fetchMe(silent = true): Promise<UserVO | null> {
    if (!token.value) return null
    try {
      const profile = await authApi.me({ silent })
      user.value = profile
      writeUser(getApiBase(), profile)
      return profile
    } catch (err) {
      if (err instanceof ApiError && (err.code === 40100 || err.httpStatus === 401)) {
        token.value = ''
        user.value = null
        clearUser(getApiBase())
      }
      return null
    }
  }

  async function restore(): Promise<boolean> {
    if (!token.value) return false
    const profile = user.value ?? (await fetchMe(true))
    return Boolean(profile ?? token.value)
  }

  function hasAnyRole(required?: string[]): boolean {
    if (!required || required.length === 0) return true
    if (isAdmin.value) return true
    return required.some((role) => roles.value.includes(role))
  }

  function syncForBackend(): void {
    refreshFromStorage()
    if (token.value && !user.value) void fetchMe(true)
  }

  function logout(): void {
    clear()
  }

  return {
    token,
    user,
    loading,
    error,
    isLoggedIn,
    displayName,
    roles,
    isAdmin,
    login,
    logout,
    clear,
    fetchMe,
    restore,
    refreshFromStorage,
    syncForBackend,
    hasAnyRole,
  }
})
