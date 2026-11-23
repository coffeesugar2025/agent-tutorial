import 'axios'

// 允许调用方按请求关闭全局错误 toast（如后台轮询、能力探测）
declare module 'axios' {
  export interface AxiosRequestConfig {
    silent?: boolean
  }
  export interface InternalAxiosRequestConfig {
    silent?: boolean
  }
}
