import type { LogisticsVO, OrderStatus, OrderVO, PageResult } from '@/types'
import { compactParams, get } from './http'

export interface OrderQuery {
  status?: OrderStatus
  page?: number
  size?: number
}

export function listOrders(query: OrderQuery = {}): Promise<PageResult<OrderVO>> {
  return get<PageResult<OrderVO>>(
    '/orders',
    compactParams({ status: query.status, page: query.page ?? 1, size: query.size ?? 20 }),
  )
}

export function getOrder(orderNo: string): Promise<OrderVO> {
  return get<OrderVO>(`/orders/${encodeURIComponent(orderNo)}`)
}

export function getLogistics(orderNo: string): Promise<LogisticsVO> {
  return get<LogisticsVO>(`/orders/${encodeURIComponent(orderNo)}/logistics`)
}
