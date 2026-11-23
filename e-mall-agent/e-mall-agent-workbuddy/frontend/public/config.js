// 运行时后端配置：docker 部署时挂载替换本文件即可切换后端，无需重新构建。
// API_BASE_URL 留空表示按默认优先级解析（Vite 环境变量 -> localStorage -> 默认地址）。
window.__APP_CONFIG__ = { API_BASE_URL: '' }
