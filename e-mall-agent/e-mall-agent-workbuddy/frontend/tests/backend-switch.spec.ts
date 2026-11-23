import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  API_BASE_KEY,
  BACKEND_KEY,
  BACKEND_PRESETS,
  DEFAULT_API_BASE_URL,
  TOKEN_KEY,
  apiUrl,
  getApiBaseUrl,
  getBackendKey,
  getBackendPreset,
  probeHealth,
  resetApiBaseUrl,
  setApiBaseUrl,
  setBackendKey,
} from '../src/api/client'
import { useAppStore } from '../src/stores/app'

describe('backend switching', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    delete window.__APP_CONFIG__
  })

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllEnvs()
    vi.unstubAllGlobals()
    delete window.__APP_CONFIG__
  })

  it('resolves baseURL with runtime > env > localStorage > default priority', () => {
    expect(getApiBaseUrl()).toBe(DEFAULT_API_BASE_URL)

    setApiBaseUrl('http://stored:9000')
    expect(localStorage.getItem(API_BASE_KEY)).toBe('http://stored:9000')
    expect(getApiBaseUrl()).toBe('http://stored:9000')

    vi.stubEnv('VITE_API_BASE_URL', 'http://env:7000')
    expect(getApiBaseUrl()).toBe('http://env:7000')

    window.__APP_CONFIG__ = { API_BASE_URL: 'http://runtime:6000' }
    expect(getApiBaseUrl()).toBe('http://runtime:6000')

    window.__APP_CONFIG__ = { API_BASE_URL: '' }
    expect(getApiBaseUrl()).toBe('http://env:7000')
  })

  it('persists backend selection and restores it on resolution', () => {
    expect(getBackendKey()).toBe('python')

    setBackendKey('java')
    expect(localStorage.getItem(BACKEND_KEY)).toBe('java')
    expect(getBackendKey()).toBe('java')
    expect(getApiBaseUrl()).toBe(getBackendPreset('java').url)

    resetApiBaseUrl()
    expect(localStorage.getItem(BACKEND_KEY)).toBeNull()
    expect(localStorage.getItem(API_BASE_KEY)).toBeNull()
    expect(getApiBaseUrl()).toBe(DEFAULT_API_BASE_URL)
  })

  it('switchBackend clears the token and updates reactive state', () => {
    setActivePinia(createPinia())
    localStorage.setItem(TOKEN_KEY, 'backend-specific-token')
    const store = useAppStore()
    expect(store.token).toBe('backend-specific-token')

    store.switchBackend('java')

    expect(store.backend).toBe('java')
    expect(store.apiBaseUrl).toBe(getBackendPreset('java').url)
    expect(store.token).toBeNull()
    expect(store.isLoggedIn).toBe(false)
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull()
  })

  it('supports preset URL overrides via Vite env variables', async () => {
    vi.stubEnv('VITE_PYTHON_API_URL', 'http://py-env:8100')
    vi.stubEnv('VITE_JAVA_API_URL', 'http://java-env:8180')
    vi.resetModules()

    const fresh = await import('../src/api/client')
    expect(BACKEND_PRESETS).toHaveLength(2)
    expect(fresh.getBackendPreset('python').url).toBe('http://py-env:8100')
    expect(fresh.getBackendPreset('java').url).toBe('http://java-env:8180')
  })

  it('builds API URLs from the resolved base', () => {
    expect(apiUrl('/health')).toBe('/api/health')

    setApiBaseUrl('http://java-host:8080/')
    expect(apiUrl('/health')).toBe('http://java-host:8080/api/health')
    expect(apiUrl('orders')).toBe('http://java-host:8080/api/orders')
  })

  it('probes GET /api/health and reports online or offline', async () => {
    setApiBaseUrl('http://java-host:8080')
    const fetchMock = vi.fn().mockResolvedValue({ ok: true })
    vi.stubGlobal('fetch', fetchMock)

    expect(await probeHealth()).toBe(true)
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('http://java-host:8080/api/health')
    expect(init.method).toBe('GET')

    fetchMock.mockRejectedValueOnce(new Error('network down'))
    expect(await probeHealth()).toBe(false)
  })
})
