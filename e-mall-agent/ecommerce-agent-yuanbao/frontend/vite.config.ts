import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

/**
 * 开发态代理必须与 src/api/backend.ts::apiBase() 对齐：
 *   /api/py/*   → Python 后端 8000，去掉 /api/py 前缀
 *   /api/java/* → Java 后端 8080，去掉 /api/java 前缀
 *   /api/*      → 默认走 Python（兼容旧调用）
 * 具体前缀必须排在 /api 之前，否则会被通配先吃掉。
 */
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api/java': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/java/, ''),
      },
      '/api/py': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/py/, ''),
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'node',
    include: ['src/__tests__/**/*.spec.ts'],
  },
})
