import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: true,
      port: 5173,
      strictPort: false,
      proxy: {
        // 默认 VITE_API_BASE=/api/v1，开发时经此代理转发到本地 Python/Java 后端
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          ws: false,
        },
        // 健康检查不走 /api/v1 前缀
        '/health': {
          target: proxyTarget,
          changeOrigin: true,
          ws: false,
        },
      },
    },
    preview: {
      host: true,
      port: 8088,
    },
    build: {
      target: 'es2020',
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 1600,
      rollupOptions: {
        output: {
          manualChunks: {
            echarts: ['echarts'],
            'element-plus': ['element-plus'],
            vendor: ['vue', 'vue-router', 'pinia', 'axios', 'dayjs', 'markdown-it'],
          },
        },
      },
    },
    test: {
      environment: 'jsdom',
      include: ['tests/**/*.spec.ts'],
      setupFiles: ['./tests/setup.ts'],
      css: false,
      restoreMocks: true,
    },
  }
})
