import dayjs from 'dayjs'
import relativeTime from 'dayjs/plugin/relativeTime'
import 'dayjs/locale/zh-cn'

dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

export type TagTone = 'success' | 'info' | 'warning' | 'danger'

export interface TagMeta {
  label: string
  tone: TagTone
}

/** 空值统一占位符 */
export const PLACEHOLDER = '—'

export function formatDateTime(value?: string | number | null): string {
  if (!value) return PLACEHOLDER
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD HH:mm:ss') : String(value)
}

export function formatDate(value?: string | number | null): string {
  if (!value) return PLACEHOLDER
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('YYYY-MM-DD') : String(value)
}

export function formatTimeShort(value?: string | number | null): string {
  if (!value) return PLACEHOLDER
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.format('MM-DD HH:mm') : String(value)
}

export function fromNow(value?: string | number | null): string {
  if (!value) return PLACEHOLDER
  const parsed = dayjs(value)
  return parsed.isValid() ? parsed.fromNow() : String(value)
}

/** 金额（单位：元）→ ¥1,299.00 */
export function formatMoney(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return PLACEHOLDER
  return `¥${value.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

/** 金额（单位：分）→ ¥12.34 */
export function formatCents(cents?: number | null): string {
  if (cents === null || cents === undefined || !Number.isFinite(cents)) return PLACEHOLDER
  return formatMoney(cents / 100)
}

/** 0.93 → 93.0% */
export function formatPercent(ratio?: number | null, digits = 1): string {
  if (ratio === null || ratio === undefined || !Number.isFinite(ratio)) return PLACEHOLDER
  return `${(ratio * 100).toFixed(digits)}%`
}

/** 0.87 → 0.87（检索分数保留三位） */
export function formatScore(score?: number | null, digits = 3): string {
  if (score === null || score === undefined || !Number.isFinite(score)) return PLACEHOLDER
  return score.toFixed(digits)
}

export function formatNumber(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return PLACEHOLDER
  return value.toLocaleString('zh-CN')
}

export function formatLatency(ms?: number | null): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return PLACEHOLDER
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

export function formatTokens(value?: number | null): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return PLACEHOLDER
  return value >= 1000 ? `${(value / 1000).toFixed(1)}k` : String(value)
}

export function formatFileSize(bytes?: number | null): string {
  if (!bytes || bytes < 0) return PLACEHOLDER
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(2)}MB`
}

export function truncate(text: string | undefined, max = 80): string {
  if (!text) return ''
  return text.length > max ? `${text.slice(0, max)}…` : text
}

/** 统一 JSON 展示（工具参数 / 审批 detail） */
export function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? 'null'
  } catch {
    return String(value)
  }
}

export function metaOf(map: Record<string, TagMeta>, value?: string | null): TagMeta {
  if (!value) return { label: '未知', tone: 'info' }
  return map[value] ?? { label: value, tone: 'info' }
}

export const AGENT_META: Record<string, TagMeta> = {
  SUPERVISOR: { label: '调度', tone: 'info' },
  SHOPPING: { label: '导购', tone: 'success' },
  SERVICE: { label: '客服', tone: 'warning' },
  OPS: { label: '运营', tone: 'danger' },
}

export const RISK_META: Record<string, TagMeta> = {
  READ: { label: '只读', tone: 'info' },
  WRITE: { label: '写入', tone: 'warning' },
  IRREVERSIBLE: { label: '不可逆', tone: 'danger' },
}

export const ORDER_STATUS_META: Record<string, TagMeta> = {
  CREATED: { label: '待支付', tone: 'info' },
  PAID: { label: '已支付', tone: 'warning' },
  SHIPPED: { label: '已发货', tone: 'warning' },
  DELIVERED: { label: '已送达', tone: 'success' },
  FINISHED: { label: '已完成', tone: 'success' },
  CANCELLED: { label: '已取消', tone: 'info' },
  REFUNDING: { label: '退款中', tone: 'danger' },
  REFUNDED: { label: '已退款', tone: 'danger' },
}

export const APPROVAL_STATUS_META: Record<string, TagMeta> = {
  PENDING: { label: '待审批', tone: 'warning' },
  APPROVED: { label: '已同意', tone: 'success' },
  REJECTED: { label: '已拒绝', tone: 'danger' },
  EXPIRED: { label: '已过期', tone: 'info' },
}

export const DOC_TYPE_META: Record<string, TagMeta> = {
  POLICY: { label: '政策', tone: 'danger' },
  MANUAL: { label: '手册', tone: 'info' },
  FAQ: { label: 'FAQ', tone: 'success' },
  PRODUCT_DOC: { label: '商品文档', tone: 'warning' },
}

export const VISIBILITY_META: Record<string, TagMeta> = {
  PUBLIC: { label: '公开', tone: 'success' },
  INTERNAL: { label: '内部', tone: 'warning' },
  ADMIN: { label: '管理员', tone: 'danger' },
}

export const DOC_STATUS_META: Record<string, TagMeta> = {
  QUEUED: { label: '排队中', tone: 'info' },
  INDEXING: { label: '索引中', tone: 'warning' },
  READY: { label: '可检索', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  DELETING: { label: '删除中', tone: 'warning' },
}

export const JOB_STATUS_META: Record<string, TagMeta> = {
  QUEUED: { label: '排队中', tone: 'info' },
  RUNNING: { label: '执行中', tone: 'warning' },
  SUCCESS: { label: '成功', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  DEAD: { label: '已死信', tone: 'danger' },
}

export const EVAL_STATUS_META: Record<string, TagMeta> = {
  QUEUED: { label: '排队中', tone: 'info' },
  RUNNING: { label: '运行中', tone: 'warning' },
  SUCCESS: { label: '成功', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  CANCELLED: { label: '已取消', tone: 'info' },
}

export const TRACE_STATUS_META: Record<string, TagMeta> = {
  SUCCESS: { label: '成功', tone: 'success' },
  FAILED: { label: '失败', tone: 'danger' },
  RUNNING: { label: '进行中', tone: 'warning' },
  PARTIAL: { label: '部分成功', tone: 'warning' },
}

export const SPAN_TYPE_META: Record<string, TagMeta> = {
  AGENT: { label: 'Agent', tone: 'info' },
  LLM: { label: 'LLM', tone: 'success' },
  TOOL: { label: '工具', tone: 'warning' },
  RAG: { label: '检索', tone: 'danger' },
  SYSTEM: { label: '系统', tone: 'info' },
}

export const CIRCUIT_META: Record<string, TagMeta> = {
  CLOSED: { label: '熔断关闭', tone: 'success' },
  HALF_OPEN: { label: '半开', tone: 'warning' },
  OPEN: { label: '熔断打开', tone: 'danger' },
}

export const FINISH_REASON_META: Record<string, TagMeta> = {
  stop: { label: '正常结束', tone: 'success' },
  interrupted: { label: '已中断', tone: 'warning' },
  approval_required: { label: '等待审批', tone: 'warning' },
  max_steps: { label: '达到最大步数', tone: 'danger' },
  error: { label: '异常结束', tone: 'danger' },
}

export const ROLE_LABELS: Record<string, string> = {
  USER: '普通用户',
  ADMIN: '管理员',
  OPS: '运营',
  SERVICE: '客服',
}
