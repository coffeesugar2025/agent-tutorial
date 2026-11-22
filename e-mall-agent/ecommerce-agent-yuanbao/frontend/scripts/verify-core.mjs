/**
 * 零依赖核心校验 —— 不需要 npm install。
 *
 * 用 Node 24+ 自带的 TypeScript 类型剥离直接执行 src/api 下的真实源码，
 * 覆盖 SSE 解析、缓冲区切分、格式化与流式客户端（含跨 chunk 还原）。
 *
 *   node --no-warnings scripts/verify-core.mjs
 *
 * 完整的组件级测试仍请用 `npm test`（vitest）。
 */
import { stripTypeScriptTypes } from 'node:module'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import assert from 'node:assert/strict'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function toPlain(p) {
  const js = stripTypeScriptTypes(readFileSync(path.join(root, p), 'utf8'), { mode: 'strip' })
  return js
    .replace(/^import[^\n]*$/gm, '')   // type-only 与值 import 全部去掉，合成到同一模块
    .replace(/\bexport\s+/g, '')
}

const code =
  toPlain('src/api/sse.ts') +
  '\n' + toPlain('src/api/client.ts') +
  '\nexport { parseSSEBlock, splitSSEBuffer, toolLabel, formatMoney, streamChat }\n'

const mod = await import('data:text/javascript;charset=utf-8,' + encodeURIComponent(code))
const { parseSSEBlock, splitSSEBuffer, toolLabel, formatMoney, streamChat } = mod

let passed = 0
const t = (name, fn) => { fn(); console.log('  ok -', name); passed++ }

t('SSE 标准事件块解析', () => {
  assert.deepEqual(parseSSEBlock('event: token\ndata: {"text":"你好"}'),
    { event: 'token', data: { text: '你好' } })
})
t('SSE CRLF / 多行 data / 注释行', () => {
  const ev = parseSSEBlock(': keep-alive\r\nevent: cards\r\ndata: {"cards":[\r\ndata: {"type":"product"}]}')
  assert.equal(ev.event, 'cards')
  assert.ok(ev.data.cards)
})
t('SSE 非法块被拒绝', () => {
  assert.equal(parseSSEBlock('event: unknown\ndata: {}'), null)
  assert.equal(parseSSEBlock('event: done\ndata: not-json'), null)
  assert.equal(parseSSEBlock('data: {"a":1}'), null)
  assert.equal(parseSSEBlock('event: meta'), null)
  assert.equal(parseSSEBlock('event: done\ndata: [1,2]'), null)
})
t('SSE 缓冲区切分保留未闭合尾部', () => {
  const { blocks, rest } = splitSSEBuffer('event: meta\ndata: {}\n\nevent: token\ndata: {"text":"部')
  assert.equal(blocks.length, 1)
  assert.ok(rest.includes('event: token'))
  assert.equal(splitSSEBuffer('event: a\r\ndata: {}\r\n\r\n\r\nevent: b\r\ndata: {}\r\n\r\n').blocks.length, 2)
})
t('工具名 / 金额格式化', () => {
  assert.equal(toolLabel('shop_search_products'), '商品检索')
  assert.equal(toolLabel('calculate_price'), '到手价计算')
  assert.equal(toolLabel('mystery_tool'), 'mystery_tool')
  assert.equal(formatMoney(799), '¥799.00')
  assert.equal(formatMoney(undefined), '—')
  assert.equal(formatMoney(10, 'USD'), '¥10.00 USD')
})

function sseResponse(chunks, status = 200) {
  const enc = new TextEncoder()
  const body = new ReadableStream({
    start(c) { for (const x of chunks) c.enqueue(enc.encode(x)); c.close() },
  })
  return new Response(status === 200 ? body : null, { status })
}
const payload = { message: '找耳机', thread_id: 't1', user_id: 'u_1001' }

globalThis.fetch = async () => sseResponse([
  'event: meta\ndata: {"thread_id":"t1"}\n\nevent: token\ndata: {"te',
  'xt":"你好"}\n\nevent: done\ndata: {"tool_calls":1}\n\n',
])
const events = []
await streamChat(payload, (e) => events.push(e))
t('streamChat 跨 chunk 还原事件序列', () => {
  assert.deepEqual(events.map((e) => e.event), ['meta', 'token', 'done'])
  assert.equal(events[1].data.text, '你好')
})

globalThis.fetch = async () => sseResponse([], 502)
await assert.rejects(() => streamChat(payload, () => {}), /HTTP 502/)
console.log('  ok - streamChat 非 200 抛错'); passed++

globalThis.fetch = async () => sseResponse([
  'event: bogus\ndata: {}\n\nevent: error\ndata: {"message":"boom"}\n\n',
])
const filtered = []
await streamChat(payload, (e) => filtered.push(e))
t('streamChat 过滤非法事件并保留合法事件', () => {
  assert.equal(filtered.length, 1)
  assert.equal(filtered[0].event, 'error')
})

console.log(`\nFRONTEND CORE: ${passed} assertions passed (zero npm dependencies)`)
