export interface User {
  id: string
  name: string
  role: string
  permissions: string[]
}

export interface LoginResult {
  token: string
  user_id: string
  role: string
  permissions: string[]
}

export interface Product {
  id: string
  name: string
  category: string
  price: number
  stock: number
  tags: string[]
  description: string
}

export interface OrderItem {
  product_id: string
  quantity: number
  unit_price: number
}

export interface Order {
  id: string
  customer_id: string
  items: OrderItem[]
  total: number
  status: string
  created_at: string
  address?: string
}

export interface ContextSection {
  name: string
  chars: number
  included: boolean
  priority?: number
  truncated?: boolean
}

export interface ContextSnapshot {
  sections: ContextSection[]
  max_chars: number
  total_chars: number
  kept_messages: number
  dropped_messages: number
  compressed: boolean
}

export interface ChatResult {
  answer: string
  route: string
  trace_id: string
  context: ContextSnapshot | Record<string, unknown>
}

export interface ToolCall {
  name: string
  content: string
}

export type ChatEvent =
  | { event: 'node'; node: string }
  | { event: 'route'; data: string }
  | { event: 'context'; data: ContextSnapshot }
  | { event: 'tool'; data: ToolCall }
  | { event: 'token'; data: string }
  | { event: 'done'; data: string }
  | { event: 'error'; data: string }

export interface GraphNode {
  id: string
  label: string
  kind: string
}

export interface GraphEdge {
  source: string
  target: string
  label?: string
}

export interface GraphDescription {
  title: string
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface GraphBundle {
  supervisor: GraphDescription
  fulfillment: GraphDescription
}

export interface TraceEvent {
  ts: number
  trace_id: string
  node: string
  event: string
  payload: unknown
}

export interface AuditEntry {
  ts: string | number
  actor: string
  action: string
  resource: string
  decision: string
  detail: string
}

export interface ContextPreview {
  snapshot: ContextSnapshot
  messages: Array<{ role: string; content: string }>
}

export interface RagDoc {
  source: string
  content: string
  category: string
}

export interface ApprovalInterrupt {
  kind: string
  order_id: string
  amount: number
  reason: string
}

export interface FulfillmentResult {
  thread_id: string
  status: string
  message: string
  steps: string[]
  interrupt?: ApprovalInterrupt
}
