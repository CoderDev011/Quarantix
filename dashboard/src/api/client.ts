// Thin fetch wrapper for the control-plane API. Types come from ./types.ts, which is
// generated from the API's OpenAPI (scripts/gen_types.sh) and never edited by hand.
import type { components } from './types.ts'

export type EventOut = components['schemas']['EventOut']
export type DecisionOut = components['schemas']['DecisionOut']
export type LabelOut = components['schemas']['LabelOut']
export type ArgPreviewOut = components['schemas']['ArgPreviewOut']
export type ProvenanceOut = components['schemas']['ProvenanceOut']
export type AgentOut = components['schemas']['AgentOut']
export type ApprovalOut = components['schemas']['ApprovalOut']

export class ApiError extends Error {
  readonly status: number
  readonly code: string

  constructor(status: number, code: string, message: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin', // the HttpOnly admin cookie rides along
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  })
  if (!response.ok) {
    let code = 'error'
    let message = response.statusText
    try {
      const body = (await response.json()) as { error?: string; message?: string }
      code = body.error ?? code
      message = body.message ?? message
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, code, message)
  }
  return (await response.json()) as T
}

export const login = (token: string) =>
  api<{ ok: boolean }>('/v1/session', { method: 'POST', body: JSON.stringify({ token }) })

export const setMode = (agent: string, mode: AgentOut['mode']) =>
  api<{ bundle_version: string }>(`/v1/agents/${encodeURIComponent(agent)}/mode`, {
    method: 'PUT',
    body: JSON.stringify({ mode }),
  })

export const resolveApproval = (id: string, verdict: 'approve' | 'deny', scope: 'once' | 'run' = 'once') =>
  api<{ id: string }>(`/v1/approvals/${encodeURIComponent(id)}/resolve`, {
    method: 'POST',
    body: JSON.stringify({ verdict, scope }),
  })
