import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 前后端分离开发：/api 代理到 FastAPI（uvicorn 默认 8000）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
