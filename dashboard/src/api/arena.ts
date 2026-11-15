// Arena, Autopilot, proof and domain-generator calls. Types are generated (types.ts).
import { api } from './client.ts'
import type { components } from './types.ts'

type S = components['schemas']
export type AttemptOut = S['AttemptOut']
export type AdminAttemptOut = S['AdminAttemptOut']
export type DefenderOut = S['DefenderOut']
export type GoalOut = S['GoalOut']
export type LeaderRowOut = S['LeaderRowOut']
export type ArenaStatsOut = S['ArenaStatsOut']
export type AutopilotProgressOut = S['AutopilotProgressOut']
export type ProposalOut = S['ProposalOut']
export type ProofOut = S['ProofOut']
export type RateOut = S['RateOut']
export type ProofReportOut = S['ProofReportOut']
export type DraftOut = S['DraftOut']
export type ResetOut = S['ResetOut']

const json = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) })

export const arena = {
  goals: () => api<S['GoalsPage']>('/v1/arena/goals'),
  submit: (body: { domain: string; goal_id: string; payload: string; nickname: string }) =>
    api<AttemptOut>('/v1/arena/attempts', json(body)),
  attempt: (id: string, wait = 0) =>
    api<AttemptOut>(`/v1/arena/attempts/${encodeURIComponent(id)}?wait=${wait}`),
  progress: (id: string) => api<AutopilotProgressOut>(`/v1/arena/attempts/${encodeURIComponent(id)}/autopilot`),
  leaderboard: () => api<S['LeaderboardPage']>('/v1/arena/leaderboard'),
  stats: () => api<ArenaStatsOut>('/v1/arena/stats'),
  adminAttempts: () => api<S['AdminAttemptsPage']>('/v1/arena/admin/attempts?limit=100'),
  hide: (body: { attempt_id?: string; player_id?: string }) => api<{ ok: boolean }>('/v1/arena/admin/hide', json(body)),
  pause: () => api<{ paused: boolean }>('/v1/arena/admin/pause', { method: 'POST' }),
  resume: () => api<{ paused: boolean }>('/v1/arena/admin/resume', { method: 'POST' }),
  reset: (clear_leaderboard = false) => api<ResetOut>('/v1/arena/admin/reset', json({ clear_leaderboard })),
}

export const autopilot = {
  proposals: () => api<S['ProposalsPage']>('/v1/autopilot/proposals'),
  enable: (id: string) =>
    api<ProposalOut>(`/v1/autopilot/proposals/${encodeURIComponent(id)}/enable`, json({ by: 'human:console' })),
  reject: (id: string) => api<ProposalOut>(`/v1/autopilot/proposals/${encodeURIComponent(id)}/reject`, { method: 'POST' }),
  rollback: (id: string) =>
    api<ProposalOut>(`/v1/autopilot/proposals/${encodeURIComponent(id)}/rollback`, { method: 'POST' }),
  settings: () => api<S['AutopilotSettingsOut']>('/v1/autopilot/settings'),
  setAutonomous: (autonomous: boolean) =>
    api<S['AutopilotSettingsOut']>('/v1/autopilot/settings', { method: 'PUT', body: JSON.stringify({ autonomous }) }),
}

export const proof = { run: () => api<ProofReportOut>('/v1/proof') }

export const domains = {
  generate: (description: string) => api<DraftOut>('/v1/domains/generate', json({ description })),
  confirm: (id: string) => api<DraftOut>(`/v1/domains/drafts/${encodeURIComponent(id)}/confirm`, { method: 'POST' }),
}

/** One plain sentence for a defender's outcome (phone and screen). */
export function reasonFor(result: DefenderOut | null | undefined): string {
  if (!result) return 'Waiting…'
  const rule = result.rule ?? ''
  switch (result.outcome) {
    case 'breached':
      return 'The agent did what your text asked.'
    case 'neutralized':
      return 'Your text had no effect on what the agent did.'
    case 'error':
      return 'Something failed on our side (no points for this one).'
    case 'needs_approval':
      return 'Untrusted text shaped a risky action, so it needed a person, who said no.'
  }
  if (rule.includes('C1')) return 'AgentWall saw that value came from text you wrote, not from the company.'
  if (rule.includes('C2')) return 'That data was too private for where it was going.'
  if (rule.includes('C3')) return 'Untrusted text shaped a high-risk action, so it needed a person.'
  if (rule.includes('no-foreign-links')) return 'A rule Autopilot learned: no links to unknown sites from untrusted text.'
  if (rule.startsWith('autopilot-')) return 'A rule Autopilot learned from an earlier attack stopped it.'
  return `A policy rule stopped it (${rule}).`
}

export const OUTCOME_ICON: Record<DefenderOut['outcome'], string> = {
  breached: '💥',
  blocked: '🛡️',
  neutralized: '⚪',
  needs_approval: '✋',
  error: '⚠️',
}
