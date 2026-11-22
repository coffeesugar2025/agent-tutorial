import { describe, expect, it } from 'vitest'
import { formatMoney, parseSSEBlock, splitSSEBuffer, toolLabel } from '../api/sse'
import { INTENT_LABELS } from '../types'

describe('parseSSEBlock', () => {
  it('解析标准事件块', () => {
    const ev = parseSSEBlock('event: token\ndata: {"text":"你好"}')
    expect(ev).toEqual({ event: 'token', data: { text: '你好' } })
  })

  it('支持 CRLF、多行 data 与注释行', () => {
    const ev = parseSSEBlock(': keep-alive\r\nevent: cards\r\ndata: {"cards":[\r\ndata: {"type":"product"}]}')
    expect(ev?.event).toBe('cards')
    expect(ev?.data).toHaveProperty('cards')
  })

  it('忽略未知事件与非法 JSON', () => {
    expect(parseSSEBlock('event: unknown\ndata: {}')).toBeNull()
    expect(parseSSEBlock('event: done\ndata: not-json')).toBeNull()
    expect(parseSSEBlock('data: {"a":1}')).toBeNull()
    expect(parseSSEBlock('event: meta')).toBeNull()
  })

  it('拒绝非对象 data', () => {
    expect(parseSSEBlock('event: done\ndata: [1,2]')).toBeNull()
  })
})

describe('splitSSEBuffer', () => {
  it('切出完整块并保留未闭合尾部', () => {
    const buffer = 'event: meta\ndata: {}\n\nevent: token\ndata: {"text":"部'
    const { blocks, rest } = splitSSEBuffer(buffer)
    expect(blocks).toHaveLength(1)
    expect(blocks[0]).toContain('event: meta')
    expect(rest).toContain('event: token')
  })

  it('规范化 CRLF 并过滤空块', () => {
    const { blocks } = splitSSEBuffer('event: a\r\ndata: {}\r\n\r\n\r\nevent: b\r\ndata: {}\r\n\r\n')
    expect(blocks).toHaveLength(2)
  })
})

describe('展示辅助函数', () => {
  it('工具名支持 MCP 前缀隔离', () => {
    expect(toolLabel('shop_search_products')).toBe('商品检索')
    expect(toolLabel('calculate_price')).toBe('到手价计算')
    expect(toolLabel('mystery_tool')).toBe('mystery_tool')
  })

  it('金额格式化', () => {
    expect(formatMoney(799)).toBe('¥799.00')
    expect(formatMoney(undefined)).toBe('—')
    expect(formatMoney(10, 'USD')).toBe('¥10.00 USD')
  })

  it('意图标签表完整', () => {
    expect(Object.keys(INTENT_LABELS)).toHaveLength(6)
    expect(INTENT_LABELS.price_calc).toBe('价格计算')
  })
})
