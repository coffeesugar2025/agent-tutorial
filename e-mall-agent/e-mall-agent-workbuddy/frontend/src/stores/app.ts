import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as api from '../api/client'
import type { LoginResult, User } from '../types'

export const useAppStore = defineStore('app', () => {
  const token = ref<string | null>(api.getToken())
  const user = ref<User | null>(null)
  const isLoggedIn = computed(() => Boolean(token.value))

  const backend = ref<api.BackendKey>(api.getBackendKey())
  const apiBaseUrl = ref<string>(api.getApiBaseUrl())

  /** Switch between the Python and Java backends. Tokens are not portable. */
  function switchBackend(key: api.BackendKey): void {
    api.setBackendKey(key)
    backend.value = key
    apiBaseUrl.value = api.getApiBaseUrl()
    api.clearToken()
    token.value = null
    user.value = null
  }

  async function loadMe(): Promise<User | null> {
    if (!token.value) return null
    user.value = await api.me()
    return user.value
  }

  async function login(username: string, password: string): Promise<LoginResult> {
    const result = await api.login(username, password)
    token.value = result.token
    user.value = {
      id: result.user_id,
      name: username,
      role: result.role,
      permissions: result.permissions,
    }
    try {
      await loadMe()
    } catch {
      // The login itself succeeded; keep the basic profile from the login response.
    }
    return result
  }

  function logout(): void {
    api.clearToken()
    token.value = null
    user.value = null
  }

  return { token, user, isLoggedIn, backend, apiBaseUrl, login, logout, loadMe, switchBackend }
})
