/** 纯函数 SSE 解析层：与网络解耦，便于单元测试。 */

import type { AgentEvent, EventKind } from '../types'

const VALID_EVENTS: EventKind[] = ['meta', 'token', 'tool_start', 'tool_end', 'cards', 'error', 'done']

/** 把一个完整 `event: x\ndata: {...}` 块解析成事件；非法块返回 null。 */
export function parseSSEBlock(block: string): AgentEvent | null {
  const lines = block.split(/\r?\n/)
  let event: string | undefined
  const dataLines: string[] = []

  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
    // 忽略 id: / retry: / 注释行
  }
  if (!event || !dataLines.length || !VALID_EVENTS.includes(event as EventKind)) return null
  try {
    const parsed = JSON.parse(dataLines.join('\n'))
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null
    return { event: event as EventKind, data: parsed as Record<string, unknown> }
  } catch {
    return null
  }
}

/** 从流式 buffer 中切出完整块，保留未闭合的尾部。 */
export function splitSSEBuffer(buffer: string): { blocks: string[]; rest: string } {
  const normalized = buffer.replace(/\r\n/g, '\n')
  const parts = normalized.split('\n\n')
  const rest = parts.pop() ?? ''
  return { blocks: parts.filter((b) => b.trim().length > 0), rest }
}

/** 把后端工具名映射成中文短标签。 */
export function toolLabel(name: string): string {
  const map: Record<string, string> = {
    search_products: '商品检索',
    get_product: '商品详情',
    check_inventory: '库存查询',
    get_order: '订单查询',
    list_user_orders: '我的订单',
    list_coupons: '优惠券列表',
    calculate_price: '到手价计算',
    get_after_sale_policy: '售后政策',
    check_after_sale_eligibility: '退货资格判定',
    recommend_products: '智能推荐',
  }
  const key = Object.keys(map).find((k) => name.includes(k))
  return key ? map[key] : name
}

export function formatMoney(value: number | undefined, currency = 'CNY'): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—'
  return `¥${value.toFixed(2)}${currency === 'CNY' ? '' : ` ${currency}`}`
}
