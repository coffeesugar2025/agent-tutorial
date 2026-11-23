import type {
  ApprovalDecisionRequest,
  ApprovalDecisionResult,
  ApprovalStatus,
  ApprovalVO,
  InterruptResult,
  MessageVO,
  SessionVO,
} from '@/types'
import { compactParams, del, get, post } from './http'

export function listSessions(): Promise<SessionVO[]> {
  return get<SessionVO[]>('/chat/sessions')
}

export function createSession(title?: string): Promise<SessionVO> {
  return post<SessionVO>('/chat/sessions', title ? { title } : {})
}

export function getSession(sessionId: number): Promise<SessionVO> {
  return get<SessionVO>(`/chat/sessions/${sessionId}`)
}

export function deleteSession(sessionId: number): Promise<null> {
  return del<null>(`/chat/sessions/${sessionId}`)
}

export function listMessages(sessionId: number, limit = 50): Promise<MessageVO[]> {
  return get<MessageVO[]>(`/chat/sessions/${sessionId}/messages`, { limit })
}

export function interruptSession(sessionId: number): Promise<InterruptResult> {
  return post<InterruptResult>(`/chat/sessions/${sessionId}/interrupt`, {}, { silent: true })
}

export function listApprovals(status: ApprovalStatus = 'PENDING'): Promise<ApprovalVO[]> {
  return get<ApprovalVO[]>('/chat/approvals', compactParams({ status }))
}

export function decideApproval(
  approvalId: number,
  payload: ApprovalDecisionRequest,
): Promise<ApprovalDecisionResult> {
  return post<ApprovalDecisionResult>(`/chat/approvals/${approvalId}`, payload)
}
