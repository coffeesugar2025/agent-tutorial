/** 商品与订单领域类型 */

export interface ProductVO {
  id: number
  sku: string
  title: string
  subtitle?: string
  brand?: string
  categoryId?: number
  categoryName?: string
  price: number
  originalPrice?: number
  stock: number
  rating?: number
  sales?: number
  imageUrl?: string
  attrs?: Record<string, string>
  status: number
  description?: string
}

export interface ProductQuery {
  keyword?: string
  categoryId?: number
  minPrice?: number
  maxPrice?: number
  page?: number
  size?: number
}

export interface ProductSearchRequest {
  query: string
  topK?: number
  maxPrice?: number
  brands?: string[]
}

export interface ProductSearchItem {
  sku: string
  title: string
  price: number
  score: number
  reason?: string
}

export interface ProductSearchResult {
  items: ProductSearchItem[]
  strategy: string
}

export const ORDER_STATUSES = [
  'CREATED',
  'PAID',
  'SHIPPED',
  'DELIVERED',
  'FINISHED',
  'CANCELLED',
  'REFUNDING',
  'REFUNDED',
] as const
export type OrderStatus = (typeof ORDER_STATUSES)[number]

export interface OrderItemVO {
  sku: string
  title: string
  price: number
  quantity: number
}

export interface OrderVO {
  id: number
  orderNo: string
  status: OrderStatus
  totalAmount: number
  payAmount: number
  receiverName?: string
  receiverPhone?: string
  createdAt: string
  items: OrderItemVO[]
}

export interface LogisticsEventVO {
  time: string
  desc: string
}

export interface LogisticsVO {
  company: string
  trackingNo: string
  status: string
  latestEvent?: string
  events: LogisticsEventVO[]
}
