// Live page: status chips and agents on top; the feed on the left; the selected call's
// reason and data-path graph on the right (newest blocked by default); pending approvals
// float as a card in the corner. The event stream itself is opened by AppShell.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useVirtualizer } from '@tanstack/react-virtual'
import { lazy, Suspense, useMemo, useRef } from 'react'
import { type AgentOut, type ApprovalOut, api, type EventOut, resolveApproval, setMode } from '../api/client.ts'
import { ArgChip, VerdictBadge } from '../components/labels.tsx'
import { Icon } from '../components/ui/Icon.tsx'
import { EmptyState, IconDot, PageHeader, Segmented, Skeleton, StatChip } from '../components/ui/primitives.tsx'
import { isStopped, useEvents } from '../store/events.ts'

const PathGraph = lazy(() => import('../components/PathGraph.tsx'))
const MODES = ['off', 'monitor', 'enforce'] as const satisfies readonly AgentOut['mode'][]
const MODE_TONE: Record<AgentOut['mode'], string> = {
  enforce: 'bg-ink text-white shadow-soft',
  monitor: 'bg-amber text-ink shadow-soft',
  off: 'bg-white text-ink shadow-soft',
}

export default function Live() {
  const events = useEvents((s) => s.events)
  const calls = useMemo(() => events.filter((e) => e.kind === 'tool.call').reverse(), [events])
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Overview"
        title="Live"
        subtitle="Every tool call your agents make, with the firewall’s decision as it happens."
      />
      <Counters calls={calls} />
      <Agents />
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
        <Feed calls={calls} />
        <Detail calls={calls} />
      </div>
      <Approvals />
    </div>
  )
}

function Counters({ calls }: { calls: EventOut[] }) {
  const blocked = calls.filter((e) => e.outcome === 'blocked').length
  const would = calls.filter((e) => e.decision && !e.decision.enforced && e.decision.kind !== 'allow').length
  const asked = calls.filter((e) => e.decision?.kind === 'ask').length
  return (
    <div className="animate-rise flex flex-wrap gap-3" style={{ animationDelay: '60ms' }}>
      <StatChip icon="activity" tone="ink" value={calls.length} label="Tool calls" />
      <StatChip icon="shieldX" tone="rose" value={blocked} label="Blocked" />
      <StatChip icon="hand" tone="sky" value={asked} label="Asked a person" />
      <StatChip icon="eye" tone="amber" value={would} label="Would block" />
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
  const list = agents.data?.agents
  return (
    <section className="animate-rise" style={{ animationDelay: '120ms' }}>
      <h2 className="mb-3 text-lg font-semibold">Agents</h2>
      {!list && (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-[120px] rounded-3xl" />
          ))}
        </div>
      )}
      {list?.length === 0 && <p className="text-sm text-ink-3">No agents configured.</p>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {list?.map((agent) => (
          <div
            key={agent.name}
            className={`flex flex-col gap-4 rounded-3xl p-4 shadow-soft transition duration-300 hover:-translate-y-0.5 hover:shadow-lift ${
              agent.mode === 'off' ? 'bg-surface/60' : 'bg-surface'
            }`}
          >
            <div className="flex items-center gap-3">
              <IconDot icon="robot" tone={agent.mode === 'enforce' ? 'ink' : agent.mode === 'monitor' ? 'amber' : 'neutral'} />
              <div className="min-w-0">
                <p className="truncate font-semibold">{agent.name}</p>
                <p className="font-mono text-[11px] text-ink-3">policy {agent.policy_version}</p>
              </div>
              <span
                className={`ml-auto flex items-center gap-1.5 rounded-full px-2 py-1 text-[11px] font-semibold ${
                  agent.online ? 'bg-mint/15 text-[#0b7a54]' : 'bg-surface-2 text-ink-3'
                }`}
              >
                <span className={`h-1.5 w-1.5 rounded-full ${agent.online ? 'animate-pulse bg-mint' : 'bg-ink-3'}`} />
                {agent.online ? 'Online' : 'Offline'}
              </span>
            </div>
            <Segmented
              options={MODES}
              value={agent.mode}
              onChange={(mode) => change.mutate({ agent: agent.name, mode })}
              tone={(mode) => MODE_TONE[mode]}
            />
          </div>
        ))}
      </div>
    </section>
  )
}

function Feed({ calls }: { calls: EventOut[] }) {
  const parent = useRef<HTMLDivElement>(null)
  const select = useEvents((s) => s.select)
  const selectedSeq = useEvents((s) => s.selectedSeq)
  const rows = useVirtualizer({ count: calls.length, getScrollElement: () => parent.current, estimateSize: () => 78 })
  return (
    <section className="card flex h-[620px] flex-col overflow-hidden">
      <header className="flex items-center gap-3 px-6 pt-5 pb-3">
        <h2 className="text-lg font-semibold">Activity</h2>
        <span className="chip">{calls.length.toLocaleString()} calls</span>
        {selectedSeq !== null && (
          <button type="button" onClick={() => select(null)} className="btn btn-soft ml-auto px-3 py-1 text-xs">
            <Icon name="bolt" size={13} /> Follow newest block
          </button>
        )}
      </header>
      <div ref={parent} className="min-h-0 flex-1 overflow-auto px-3 pb-3">
        {calls.length === 0 && (
          <EmptyState icon="activity" title="Waiting for tool calls">
            Run an agent or the demo feed and calls appear here the moment they’re decided.
          </EmptyState>
        )}
        <div style={{ height: rows.getTotalSize(), position: 'relative' }}>
          {rows.getVirtualItems().map((row) => {
            const event = calls[row.index]
            const active = selectedSeq === event.seq
            const stopped = isStopped(event)
            return (
              <button
                type="button"
                key={event.seq}
                onClick={() => select(event.seq ?? null)}
                className="absolute left-0 w-full p-1 text-left"
                style={{ top: row.start, height: row.size }}
              >
                <div
                  className={`flex h-full flex-col justify-center gap-1.5 rounded-2xl px-3.5 transition duration-200 ${
                    active ? 'bg-ink text-white' : 'hover:bg-surface-2'
                  } ${row.index === 0 ? 'animate-rise' : ''}`}
                >
                  <div className="flex items-center gap-2 text-sm">
                    <span
                      className={`h-2 w-2 shrink-0 rounded-full ${stopped ? 'bg-rose' : event.decision?.kind === 'ask' ? 'bg-sky' : 'bg-mint'}`}
                    />
                    <span className="font-mono font-medium">{event.tool}</span>
                    <VerdictBadge event={event} />
                    <span className={`truncate text-xs ${active ? 'text-white/60' : 'text-ink-3'}`}>{event.agent}</span>
                    <span className={`ml-auto font-mono text-[11px] ${active ? 'text-white/50' : 'text-ink-3'}`}>
                      {event.time.slice(11, 19)}
                    </span>
                  </div>
                  <div className="flex gap-1 overflow-hidden">
                    {Object.entries(event.args ?? {}).map(([name, arg]) => (
                      <ArgChip key={name} name={name} arg={arg} />
                    ))}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </div>
    </section>
  )
}

function Detail({ calls }: { calls: EventOut[] }) {
  const selectedSeq = useEvents((s) => s.selectedSeq)
  const event = selectedSeq === null ? calls.find(isStopped) : calls.find((e) => e.seq === selectedSeq)
  if (!event) {
    return (
      <section className="card flex h-[620px] items-center justify-center">
        <EmptyState icon="shieldCheck" title="Nothing stopped yet">
          Blocked calls appear here with the reason and the data path that explains them.
        </EmptyState>
      </section>
    )
  }
  const decision = event.decision
  const stopped = isStopped(event)
  return (
    <section key={event.seq} className="card animate-rise flex min-h-[620px] flex-col gap-5 p-6">
      <div className="flex items-start gap-3">
        <IconDot icon={stopped ? 'shieldX' : decision?.kind === 'ask' ? 'hand' : 'shieldCheck'} tone={stopped ? 'rose' : decision?.kind === 'ask' ? 'sky' : 'mint'} size={48} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-mono text-xl font-semibold">{event.tool}</h2>
            <VerdictBadge event={event} />
          </div>
          <p className="mt-0.5 truncate text-xs text-ink-3">
            {event.agent} · run {event.run_id} · {event.time.slice(11, 19)}
          </p>
        </div>
      </div>
      {decision && (
        <div className="rounded-3xl bg-surface-2 p-5">
          <p className="eyebrow mb-2">Why</p>
          <p className="text-[17px] leading-relaxed">{decision.reason}</p>
          <p className="mt-3 inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-1 font-mono text-xs text-ink-2">
            <Icon name="file" size={12} /> rule {decision.rule}
          </p>
        </div>
      )}
      <div>
        <p className="eyebrow mb-2">Arguments</p>
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(event.args ?? {}).map(([name, arg]) => (
            <ArgChip key={name} name={name} arg={arg} />
          ))}
        </div>
      </div>
      <div className="flex-1">
        <p className="eyebrow mb-2">Data path</p>
        {decision?.provenance ? (
          <Suspense fallback={<Skeleton className="h-80 rounded-3xl" />}>
            <PathGraph provenance={decision.provenance} offendingArg={decision.offending_arg} />
          </Suspense>
        ) : (
          <p className="rounded-3xl bg-surface-2 p-5 text-sm text-ink-3">No data path recorded for this call.</p>
        )}
      </div>
    </section>
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
    <aside className="animate-slide-in-right fixed right-4 bottom-20 z-50 w-[min(380px,calc(100vw-2rem))] md:bottom-6">
      <div className="max-h-[60vh] overflow-auto rounded-4xl bg-surface p-5 shadow-[0_30px_60px_-20px_rgb(12_13_18/0.45)] ring-1 ring-black/5">
        <div className="mb-3 flex items-center gap-3">
          <span className="relative flex">
            <span className="animate-ring-pulse absolute inset-0 rounded-full bg-sky/50" />
            <IconDot icon="hand" tone="sky" />
          </span>
          <div>
            <p className="font-semibold">Waiting for approval</p>
            <p className="text-xs text-ink-3">{pending.length} risky action{pending.length > 1 ? 's' : ''} paused</p>
          </div>
        </div>
        <div className="flex flex-col gap-2">
          {pending.map((item) => (
            <div key={item.id} className="rounded-3xl bg-surface-2 p-4">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-semibold">{item.tool}</span>
                <span className="truncate text-xs text-ink-3">{item.agent}</span>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-ink-2">{item.reason}</p>
              <div className="mt-3 flex gap-2">
                <button
                  type="button"
                  disabled={resolve.isPending}
                  onClick={() => resolve.mutate({ id: item.id, verdict: 'approve' })}
                  className="btn btn-ink flex-1 py-1.5 text-xs"
                >
                  <Icon name="check" size={13} /> Approve
                </button>
                <button
                  type="button"
                  disabled={resolve.isPending}
                  onClick={() => resolve.mutate({ id: item.id, verdict: 'deny' })}
                  className="btn btn-ghost flex-1 py-1.5 text-xs"
                >
                  <Icon name="x" size={13} /> Deny
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </aside>
  )
}
