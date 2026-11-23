import type {
  CapabilitiesVO,
  CostVO,
  EvalRunCreatedVO,
  EvalRunRequest,
  EvalRunVO,
  HealthVO,
  ModelHealthVO,
  OverviewVO,
  TraceDetailVO,
  TraceVO,
} from '@/types'
import { compactParams, get, getApiBase, post, request } from './http'

export function getOverview(days = 7): Promise<OverviewVO> {
  return get<OverviewVO>('/admin/overview', { days })
}

export interface TraceQuery {
  sessionId?: number
  status?: string
  limit?: number
}

export function listTraces(query: TraceQuery = {}): Promise<TraceVO[]> {
  return get<TraceVO[]>(
    '/admin/traces',
    compactParams({ sessionId: query.sessionId, status: query.status, limit: query.limit ?? 20 }),
  )
}

export function getTrace(traceId: string): Promise<TraceDetailVO> {
  return get<TraceDetailVO>(`/admin/traces/${encodeURIComponent(traceId)}`)
}

export function getCosts(days = 7): Promise<CostVO> {
  return get<CostVO>('/admin/costs', { days })
}

export function getModelHealth(): Promise<ModelHealthVO[]> {
  return get<ModelHealthVO[]>('/admin/models')
}

export function runEval(payload: EvalRunRequest): Promise<EvalRunCreatedVO> {
  return post<EvalRunCreatedVO>('/admin/evals/run', payload)
}

export function listEvalRuns(): Promise<EvalRunVO[]> {
  return get<EvalRunVO[]>('/admin/evals/runs')
}

export function getEvalRun(runId: number): Promise<EvalRunVO> {
  return get<EvalRunVO>(`/admin/evals/runs/${runId}`, undefined, { silent: true })
}

/** 后端能力探测：设置页与导航栏标签的数据源 */
export function getCapabilities(): Promise<CapabilitiesVO> {
  return get<CapabilitiesVO>('/meta/capabilities', undefined, { silent: true })
}

/** /health 不在 /api/v1 前缀下，需要回退到站点根 */
export function getHealth(): Promise<HealthVO> {
  const base = getApiBase()
  const origin = /^https?:\/\//i.test(base) ? new URL(base).origin : window.location.origin
  return request<HealthVO>({ url: `${origin}/health`, method: 'GET', silent: true })
}
