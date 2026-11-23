/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
  readonly VITE_PYTHON_API_URL?: string
  readonly VITE_JAVA_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

interface Window {
  /** Injected at runtime by nginx/container via /config.js. Empty means use default resolution. */
  __APP_CONFIG__?: {
    API_BASE_URL?: string
  }
}
