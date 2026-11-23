/** 运营可观测与评测 */
import type { AgentType } from './chat'

export const TRACE_STATUSES = ['SUCCESS', 'FAILED', 'RUNNING', 'PARTIAL'] as const
export type TraceStatus = (typeof TRACE_STATUSES)[number]

export const SPAN_TYPES = ['AGENT', 'LLM', 'TOOL', 'RAG', 'SYSTEM'] as const
export type SpanType = (typeof SPAN_TYPES)[number]

export const SPAN_STATUSES = ['OK', 'ERROR', 'RUNNING'] as const
export type SpanStatus = (typeof SPAN_STATUSES)[number]

export const CIRCUIT_STATES = ['CLOSED', 'OPEN', 'HALF_OPEN'] as const
export type CircuitState = (typeof CIRCUIT_STATES)[number]
export type ModelRole = 'primary' | 'fallback' | 'embedding' | 'rerank'

export interface TopToolVO {
  name: string
  count: number
}

export interface TrendPointVO {
  date: string
  sessions: number
  costCents: number
}

export interface OverviewVO {
  totalSessions: number
  totalMessages: number
  successRate: number
  avgLatencyMs: number
  p95LatencyMs: number
  totalCostCents: number
  costPerSuccessCents: number
  approvalPending: number
  toolErrorRate: number
  topTools: TopToolVO[]
  trend: TrendPointVO[]
}

export interface TraceVO {
  traceId: string
  sessionId: number
  agentType: AgentType
  status: TraceStatus
  totalLatencyMs: number
  totalCostCents: number
  stepCount: number
  createdAt?: string
}

export interface SpanVO {
  spanId: string
  parentSpanId: string | null
  name: string
  spanType: SpanType
  seq: number
  input?: Record<string, unknown>
  output?: Record<string, unknown>
  latencyMs: number
  status: SpanStatus
}

export interface TraceDetailVO {
  trace: TraceVO
  spans: SpanVO[]
  replayable: boolean
}

export interface ModelCostVO {
  model: string
  calls: number
  costCents: number
}

export interface ProviderCostVO {
  provider: string
  costCents: number
}

export interface DailyCostVO {
  date: string
  costCents: number
}

export interface CostVO {
  total: number
  byModel: ModelCostVO[]
  byProvider: ProviderCostVO[]
  daily: DailyCostVO[]
}

export interface ModelHealthVO {
  provider: string
  model: string
  role: ModelRole | string
  healthy: boolean
  circuit: CircuitState
  avgLatencyMs: number
  calls: number
}

export const EVAL_RUN_STATUSES = ['QUEUED', 'RUNNING', 'SUCCESS', 'FAILED', 'CANCELLED'] as const
export type EvalRunStatus = (typeof EVAL_RUN_STATUSES)[number]

export interface EvalRunRequest {
  suite: string
  repeat: number
}

export interface EvalRunCreatedVO {
  runId: number
  status: EvalRunStatus
}

export interface EvalCaseVO {
  caseId: string
  question: string
  expected: string
  actual: string
  passed: boolean
  score: number
}

export interface EvalRunVO {
  id: number
  suite: string
  status: EvalRunStatus
  total: number
  passed: number
  passRate: number
  passK: number
  avgCostCents: number
  avgLatencyMs: number
  cases?: EvalCaseVO[]
  createdAt?: string
}
