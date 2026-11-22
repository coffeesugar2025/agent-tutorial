/** 与后端 app/schemas.py 一一对应的前端契约。 */

export type EventKind = 'meta' | 'token' | 'tool_start' | 'tool_end' | 'cards' | 'error' | 'done'

export interface AgentEvent {
  event: EventKind
  data: Record<string, unknown>
}

export type CardType = 'product' | 'order' | 'price' | 'coupon' | 'policy' | 'after_sale' | 'inventory'

export interface AgentCard {
  type: CardType
  sku?: string
  title?: string
  subtitle?: string
  price?: number
  stock?: number
  in_stock?: boolean
  rating?: number
  tags?: string[]
  description?: string
  order_id?: string
  status?: string
  total?: number
  created_at?: string
  node?: string
  items?: Array<{ sku: string; name: string; qty: number; price: number }>
  subtotal?: number
  discount?: number
  payable?: number
  currency?: string
  coupons?: Array<{ code: string; title: string; amount?: number }>
  quantity?: number
  code?: string
  threshold?: number
  value?: number
  topic?: string
  content?: string
  eligible?: boolean
  reason?: string
  days_left?: number
}

export interface ToolTrace {
  index: number
  name: string
  args: Record<string, unknown>
  status: 'running' | 'success' | 'error'
  summary?: string
  elapsedMs?: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  createdAt: number
  streaming?: boolean
  intent?: string
  traces: ToolTrace[]
  cards: AgentCard[]
  error?: string
  meta?: { elapsed_ms?: number; tool_calls?: number }
}

export interface Session {
  id: string
  title: string
  createdAt: number
  messages: ChatMessage[]
}

export interface ToolInfo {
  name: string
  description: string
  source: 'mcp' | 'local'
}

export interface HealthInfo {
  status: string
  agent_mode: 'mock' | 'real'
  model: string
  mcp_transport: string
  tool_count: number
  langchain_version: string
}

export interface IntentInfo {
  intent: string
  keywords: string[]
  budget_max: number | null
  category: string | null
  needs_tool: boolean
  confidence: number
}

export const INTENT_LABELS: Record<string, string> = {
  search_product: '商品检索',
  order_query: '订单查询',
  price_calc: '价格计算',
  after_sale: '售后服务',
  recommend: '智能推荐',
  other: '闲聊',
}
