import axios from 'axios'
import { ElMessage } from 'element-plus'

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || '/api/v1',
  timeout: 15000,
})

service.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

service.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      if (body.code === 401) {
        localStorage.removeItem('access_token')
        if (location.pathname !== '/login') location.assign('/login')
      }
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(new Error(body.message))
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    if (status === 401) {
      localStorage.removeItem('access_token')
      if (location.pathname !== '/login') location.assign('/login')
    }
    ElMessage.error(error.response?.data?.message || error.message || '网络异常')
    return Promise.reject(error)
  },
)

export const http = {
  get: <T>(url: string, params?: object) =>
    service.get<unknown, T>(url, { params }),
  post: <T>(url: string, data?: object) =>
    service.post<unknown, T>(url, data),
  put: <T>(url: string, data?: object) =>
    service.put<unknown, T>(url, data),
  patch: <T>(url: string, data?: object) =>
    service.patch<unknown, T>(url, data),
  delete: <T>(url: string) =>
    service.delete<unknown, T>(url),
}

export default service
