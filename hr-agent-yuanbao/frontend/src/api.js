// 所有后端调用集中在这里：换地址、加鉴权、加 trace header 只改这一处。
const BASE = '/api'

async function request(path, options = {}) {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail || '' } catch { /* ignore */ }
    throw new Error(`${res.status} ${detail || res.statusText}`)
  }
  return res.json()
}

export const getHealth = () => request('/health')
export const getChapters = () => request('/chapters')
export const runDemo = (id, payload) =>
  request(`/demo/${id}`, { method: 'POST', body: JSON.stringify({ payload }) })
export const approve = (caseId, action) =>
  request('/hitl/approve', {
    method: 'POST',
    body: JSON.stringify({ case_id: caseId, action, approver: '李四（主管）' }),
  })
