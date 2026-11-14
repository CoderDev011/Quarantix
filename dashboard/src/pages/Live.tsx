// Live page, layout A (split view): agents and counters on top; the feed on the left;
// the selected call's reason and data-path graph on the right (newest blocked by default).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { lazy, Suspense, useMemo, useRef } from 'react'
import {
  type AgentOut,
  type ApprovalOut,
  api,
  type EventOut,
  resolveApproval,
  setMode,
} from '../api/client.ts'
import { ArgChip, VerdictBadge } from '../components/labels.tsx'
import { useEventStream } from '../hooks/useEventStream.ts'
import { isStopped, useEvents } from '../store/events.ts'

const PathGraph = lazy(() => import('../components/PathGraph.tsx'))
const MODES: AgentOut['mode'][] = ['off', 'monitor', 'enforce']

export default function Live() {
  useEventStream(true)
  const events = useEvents((s) => s.events)
  const calls = useMemo(() => events.filter((e) => e.kind === 'tool.call').reverse(), [events])
  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col gap-3">
      <Agents />
      <Counters calls={calls} />
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-3">
        <div className="flex min-h-0 flex-col gap-3">
          <Feed calls={calls} />
          <Approvals />
        </div>
        <Detail calls={calls} />
      </div>
    </div>
  )
}

function Agents() {
  const queryClient = useQueryClient()
  const agents = useQuery({
    queryKey: ['agents'],
    queryFn: () => api<{ agents: AgentOut[] }>('/v1/agents'),
    refetchInterval: 5000,
  })
  const change = useMutation({
    mutationFn: ({ agent, mode }: { agent: string; mode: AgentOut['mode'] }) => setMode(agent, mode),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['agents'] }),
  })
  return (
    <div className="flex flex-wrap gap-2">
      {agents.data?.agents.map((agent) => (
        <div key={agent.name} className="flex items-center gap-3 rounded border border-slate-800 px-3 py-2">
          <span
            className={`h-2.5 w-2.5 rounded-full ${agent.online ? 'bg-emerald-400' : 'bg-slate-600'}`}
            title={agent.online ? 'online' : 'offline'}
          />
          <span className="font-medium">{agent.name}</span>
          <div className="flex overflow-hidden rounded border border-slate-700 text-xs">
            {MODES.map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => change.mutate({ agent: agent.name, mode })}
                className={`px-2 py-1 uppercase ${
                  agent.mode === mode
                    ? mode === 'enforce'
                      ? 'bg-emerald-600'
                      : mode === 'monitor'
                        ? 'bg-amber-500 text-black'
                        : 'bg-slate-600'
                    : 'text-slate-400 hover:bg-slate-800'
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
          <span className="font-mono text-[11px] text-slate-500">policy {agent.policy_version}</span>
        </div>
      ))}
      {agents.data?.agents.length === 0 && <p className="text-sm text-slate-500">No agents configured.</p>}
    </div>
  )
}

function Counters({ calls }: { calls: EventOut[] }) {
  const connection = useEvents((s) => s.connection)
  const blocked = calls.filter((e) => e.outcome === 'blocked').length
  const would = calls.filter((e) => e.decision && !e.decision.enforced && e.decision.kind !== 'allow').length
  const asked = calls.filter((e) => e.decision?.kind === 'ask').length
  const item = (label: string, value: number, tone = 'text-slate-100') => (
    <span>
      <span className="text-slate-500">{label}</span> <span className={`font-semibold ${tone}`}>{value}</span>
    </span>
  )
  return (
    <div className="flex items-center gap-6 text-sm">
      {item('calls', calls.length)}
      {item('blocked', blocked, 'text-red-400')}
      {item('asked', asked, 'text-sky-400')}
      {item('would block', would, 'text-amber-400')}
      <span className="ml-auto flex items-center gap-2 text-xs text-slate-400">
        <span
          className={`h-2 w-2 rounded-full ${connection === 'live' ? 'bg-emerald-400' : 'animate-pulse bg-amber-400'}`}
        />
        {connection}
      </span>
    </div>
  )
}

function Feed({ calls }: { calls: EventOut[] }) {
  const parent = useRef<HTMLDivElement>(null)
  const select = useEvents((s) => s.select)
  const selectedSeq = useEvents((s) => s.selectedSeq)
  const rows = useVirtualizer({ count: calls.length, getScrollElement: () => parent.current, estimateSize: () => 64 })
  return (
    <div ref={parent} className="min-h-0 flex-1 overflow-auto rounded border border-slate-800">
      {calls.length === 0 && <p className="p-4 text-sm text-slate-500">Waiting for tool calls…</p>}
      <div style={{ height: rows.getTotalSize(), position: 'relative' }}>
        {rows.getVirtualItems().map((row) => {
          const event = calls[row.index]
          return (
            <button
              type="button"
              key={event.seq}
              onClick={() => select(event.seq ?? null)}
              className={`absolute left-0 w-full border-b border-slate-900 px-3 py-2 text-left hover:bg-slate-900 ${
                selectedSeq === event.seq ? 'bg-slate-900' : ''
              }`}
              style={{ top: row.start, height: row.size }}
            >
              <div className="flex items-center gap-2 text-sm">
                <span className="font-mono text-[11px] text-slate-500">{event.time.slice(11, 19)}</span>
                <VerdictBadge event={event} />
                <span className="font-medium">{event.tool}</span>
                <span className="truncate text-xs text-slate-500">{event.agent}</span>
              </div>
              <div className="mt-1 flex gap-1 overflow-hidden">
                {Object.entries(event.args ?? {}).map(([name, arg]) => (
                  <ArgChip key={name} name={name} arg={arg} />
                ))}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function Detail({ calls }: { calls: EventOut[] }) {
  const selectedSeq = useEvents((s) => s.selectedSeq)
  const event = selectedSeq === null ? calls.find(isStopped) : calls.find((e) => e.seq === selectedSeq)
  if (!event) {
    return (
      <div className="rounded border border-slate-800 p-4 text-sm text-slate-500">
        Blocked calls appear here with the path that explains them.
      </div>
    )
  }
  const decision = event.decision
  return (
    <div className="flex min-h-0 flex-col gap-3 overflow-auto rounded border border-slate-800 p-4">
      <div className="flex items-center gap-2">
        <VerdictBadge event={event} />
        <span className="text-lg font-semibold">{event.tool}</span>
        <span className="text-xs text-slate-500">
          {event.agent} · run {event.run_id}
        </span>
      </div>
      {decision && (
        <>
          <p className="text-base leading-relaxed text-slate-200">{decision.reason}</p>
          <p className="font-mono text-xs text-slate-500">rule {decision.rule}</p>
        </>
      )}
      <div className="flex flex-wrap gap-1">
        {Object.entries(event.args ?? {}).map(([name, arg]) => (
          <ArgChip key={name} name={name} arg={arg} />
        ))}
      </div>
      {decision?.provenance ? (
        <Suspense fallback={<p className="text-sm text-slate-500">Loading graph…</p>}>
          <PathGraph provenance={decision.provenance} offendingArg={decision.offending_arg} />
        </Suspense>
      ) : (
        <p className="text-sm text-slate-500">No data path recorded for this call.</p>
      )}
    </div>
  )
}

function Approvals() {
  const queryClient = useQueryClient()
  const approvals = useQuery({
    queryKey: ['approvals'],
    queryFn: () => api<{ approvals: ApprovalOut[] }>('/v1/approvals'),
    refetchInterval: 2000,
  })
  const resolve = useMutation({
    mutationFn: ({ id, verdict }: { id: string; verdict: 'approve' | 'deny' }) => resolveApproval(id, verdict),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['approvals'] }),
  })
  const pending = approvals.data?.approvals ?? []
  if (pending.length === 0) return null
  return (
    <div className="max-h-56 overflow-auto rounded border border-sky-800 bg-sky-950/30 p-3">
      <h2 className="mb-2 text-sm font-semibold text-sky-300">Waiting for approval ({pending.length})</h2>
      {pending.map((item) => (
        <div key={item.id} className="mb-2 rounded border border-slate-800 p-2 text-sm">
          <div className="flex items-center gap-2">
            <span className="font-medium">{item.tool}</span>
            <span className="text-xs text-slate-500">{item.agent}</span>
            <div className="ml-auto flex gap-1">
              <button
                type="button"
                onClick={() => resolve.mutate({ id: item.id, verdict: 'approve' })}
                className="rounded bg-emerald-700 px-2 py-0.5 text-xs hover:bg-emerald-600"
              >
                Approve
              </button>
              <button
                type="button"
                onClick={() => resolve.mutate({ id: item.id, verdict: 'deny' })}
                className="rounded bg-red-700 px-2 py-0.5 text-xs hover:bg-red-600"
              >
                Deny
              </button>
            </div>
          </div>
          <p className="mt-1 text-xs text-slate-400">{item.reason}</p>
        </div>
      ))}
    </div>
  )
}
