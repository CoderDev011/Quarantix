// F18 console: proposals with their rule, rationale and proof; Enable only when the proof passed.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { autopilot, type ProposalOut, type RateOut } from '../api/arena.ts'
import { ApiError } from '../api/client.ts'
import { Icon } from '../components/ui/Icon.tsx'
import {
  EmptyState,
  ErrorNote,
  IconDot,
  PageHeader,
  Pill,
  type PillTone,
  Skeleton,
  Toggle,
} from '../components/ui/primitives.tsx'

const STATUS: Record<ProposalOut['status'], { label: string; tone: PillTone }> = {
  drafted: { label: 'Drafted', tone: 'neutral' },
  proving: { label: 'Proving', tone: 'info' },
  proved_pass: { label: 'Proof passed', tone: 'good' },
  proved_fail: { label: 'Proof failed', tone: 'bad' },
  enabled: { label: 'Enabled', tone: 'ink' },
  rejected: { label: 'Rejected', tone: 'neutral' },
  rolled_back: { label: 'Rolled back', tone: 'warn' },
}

const LIFECYCLE = ['drafted', 'proving', 'proved_pass', 'enabled'] as const
const LIFECYCLE_LABEL = ['Drafted', 'Proving', 'Proved', 'Enabled']

export default function Autopilot() {
  const queryClient = useQueryClient()
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: autopilot.proposals, refetchInterval: 2000 })
  const settings = useQuery({ queryKey: ['autopilot-settings'], queryFn: autopilot.settings })
  const toggle = useMutation({
    mutationFn: (on: boolean) => autopilot.setAutonomous(on),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['autopilot-settings'] }),
  })
  const items = proposals.data?.proposals ?? []
  const autonomous = settings.data?.autonomous ?? false
  return (
    <section className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Learning"
        title="Policy Autopilot"
        subtitle="Each breach drafts a rule from a template. It ships only after it passes its proof."
      />
      <div className="animate-rise flex flex-wrap items-center gap-4 rounded-4xl bg-surface p-5 shadow-soft" style={{ animationDelay: '60ms' }}>
        <IconDot icon="sparkles" tone={autonomous ? 'brand' : 'lilac'} size={48} />
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Autonomous mode</p>
          <p className="text-sm text-ink-3">
            Tighten-only rules that pass their proof are enabled automatically, then watched by a canary.
          </p>
        </div>
        <Toggle on={autonomous} onChange={(on) => toggle.mutate(on)} label="Autonomous mode" disabled={!settings.data} />
      </div>
      {proposals.isPending && <Skeleton className="h-64 rounded-4xl" />}
      {!proposals.isPending && items.length === 0 && (
        <div className="card">
          <EmptyState icon="sparkles" title="No proposals yet">
            A breach of Guard or Full in the arena starts one automatically.
          </EmptyState>
        </div>
      )}
      {items.map((p, i) => (
        <ProposalCard key={p.proposal_id} proposal={p} index={i} />
      ))}
    </section>
  )
}

function ProposalCard({ proposal: p, index }: { proposal: ProposalOut; index: number }) {
  const queryClient = useQueryClient()
  const act = useMutation({
    mutationFn: (action: 'enable' | 'reject' | 'rollback') => autopilot[action](p.proposal_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['proposals'] }),
  })
  const proof = p.proof
  const status = STATUS[p.status]
  const reached = p.status === 'proved_fail' ? 1 : LIFECYCLE.indexOf(p.status as (typeof LIFECYCLE)[number])
  return (
    <article className="card animate-rise overflow-hidden" style={{ animationDelay: `${Math.min(index, 6) * 70}ms` }}>
      <div className="flex flex-wrap items-center gap-3 p-6 pb-4">
        <Pill tone={status.tone} icon={p.status === 'proving' ? 'refresh' : undefined}>
          {status.label}
        </Pill>
        <span className="font-semibold">
          {p.domain} <span className="text-ink-3">/</span> {p.agent}
        </span>
        <span className="text-xs text-ink-3">
          trigger {p.trigger} · drafted by {p.draft_source}
          {p.seconds_to_patch !== null && p.seconds_to_patch !== undefined && ` · patched in ${p.seconds_to_patch}s`}
          {p.enabled_by && ` · enabled by ${p.enabled_by}`}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            disabled={p.status !== 'proved_pass' || act.isPending}
            onClick={() => act.mutate('enable')}
            className="btn btn-ink"
          >
            <Icon name="check" size={15} /> Enable
          </button>
          <button
            type="button"
            disabled={!['proved_pass', 'proved_fail', 'drafted'].includes(p.status) || act.isPending}
            onClick={() => act.mutate('reject')}
            className="btn btn-ghost"
          >
            Reject
          </button>
          <button
            type="button"
            disabled={p.status !== 'enabled' || act.isPending}
            onClick={() => act.mutate('rollback')}
            className="btn bg-amber/20 text-[#94600a] hover:bg-amber/30"
          >
            <Icon name="refresh" size={15} /> Roll back
          </button>
        </div>
      </div>

      <Stepper reached={reached} failed={p.status === 'proved_fail'} />

      {act.error && (
        <div className="px-6 pt-4">
          <ErrorNote>{act.error instanceof ApiError ? act.error.message : String(act.error)}</ErrorNote>
        </div>
      )}
      <p className="px-6 pt-5 text-[15px] leading-relaxed">{p.rationale}</p>

      <div className="grid gap-5 p-6 lg:grid-cols-2">
        <div className="flex min-w-0 flex-col gap-3">
          <p className="eyebrow">Rule · built by code from a template</p>
          <div className="flex flex-wrap gap-2">
            {p.candidate_rules.map((rule, i) => (
              <span key={i} className="chip max-w-full bg-brand-soft text-brand">
                <Icon name="code" size={13} />
                <span className="font-mono font-semibold">{rule.template}</span>
                <span className="truncate font-mono text-[11px] text-brand/70">{JSON.stringify(rule.parameters)}</span>
              </span>
            ))}
          </div>
          <div className="overflow-hidden rounded-3xl bg-[#101119]">
            <div className="flex items-center gap-1.5 border-b border-white/5 px-4 py-2.5">
              <span className="h-2.5 w-2.5 rounded-full bg-rose/80" />
              <span className="h-2.5 w-2.5 rounded-full bg-amber/80" />
              <span className="h-2.5 w-2.5 rounded-full bg-mint/80" />
              <span className="ml-2 font-mono text-[11px] text-white/40">pack.yaml</span>
            </div>
            <pre className="max-h-64 overflow-auto p-4 font-mono text-xs leading-relaxed text-[#b9f5d8]">{p.pack_yaml}</pre>
          </div>
        </div>
        <div className="flex min-w-0 flex-col gap-3">
          <p className="eyebrow">
            Proof {proof ? `· ${proof.verdict} · ${proof.cases} cases · ${proof.seconds}s` : '· running'}
          </p>
          {!proof && <Skeleton className="h-40 rounded-3xl" />}
          {proof?.before && proof.after && (
            <div className="rounded-3xl bg-surface-2 p-5">
              <div className="mb-4 flex items-center gap-4 text-xs text-ink-3">
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm bg-[#c3c6d1]" /> Before
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm bg-[#2a78d6]" /> After
                </span>
              </div>
              <div className="flex flex-col gap-4">
                <Row name="Attack success" a={proof.before.asr} b={proof.after.asr} lowerIsBetter />
                <Row name="Task success" a={proof.before.tsr} b={proof.after.tsr} />
                <Row name="False blocks" a={proof.before.false_block_rate} b={proof.after.false_block_rate} lowerIsBetter />
                <Row name="Approval rate" a={proof.before.approval_rate} b={proof.after.approval_rate} lowerIsBetter />
              </div>
            </div>
          )}
          {proof?.trigger && (
            <p className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-ink-3">Trigger {proof.trigger.attempt_id}:</span>
              <span className="font-mono">{proof.trigger.before}</span>
              <Icon name="arrowRight" size={14} className="text-ink-3" />
              <span className="font-mono font-semibold">{proof.trigger.after}</span>
              <Pill tone={proof.trigger.stopped ? 'good' : 'bad'} icon={proof.trigger.stopped ? 'check' : 'x'}>
                {proof.trigger.stopped ? 'stopped' : 'not stopped'}
              </Pill>
            </p>
          )}
          {proof?.reasons && proof.reasons.length > 0 && (
            <ul className="flex flex-col gap-1.5 text-sm text-[#c42b36]">
              {proof.reasons.map((r) => (
                <li key={r} className="flex items-start gap-2">
                  <Icon name="x" size={14} className="mt-0.5 shrink-0" /> {r}
                </li>
              ))}
            </ul>
          )}
          {proof && (
            <p className="text-xs text-ink-3">
              {proof.mode} · traces: {proof.trace_sources.join(', ') || 'none'} · past decisions re-checked:{' '}
              {String(proof.decisions.checked ?? 0)}, flipped {String(proof.decisions.flipped ?? 0)}, unknown{' '}
              {String(proof.decisions.unknown ?? 0)}
            </p>
          )}
        </div>
      </div>
    </article>
  )
}

function Stepper({ reached, failed }: { reached: number; failed: boolean }) {
  return (
    <div className="mx-6 flex items-center gap-2 rounded-full bg-surface-2 p-1.5">
      {LIFECYCLE_LABEL.map((label, i) => {
        const done = i <= reached
        const bad = failed && i === 2
        return (
          <div key={label} className="flex flex-1 items-center gap-2">
            <span
              className={`flex h-7 flex-1 items-center justify-center gap-1.5 rounded-full text-xs font-semibold transition-all duration-500 ${
                bad ? 'bg-rose text-white' : done ? 'bg-ink text-white' : 'text-ink-3'
              } ${i === reached && !failed && reached < 3 ? 'animate-pulse' : ''}`}
            >
              {done && !bad && <Icon name="check" size={12} strokeWidth={3} />}
              {bad && <Icon name="x" size={12} strokeWidth={3} />}
              {bad ? 'Failed' : label}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function pct(rate: RateOut): string {
  return rate.rate === null || rate.rate === undefined ? 'n/a' : `${Math.round(rate.rate * 100)}% (${rate.k}/${rate.n})`
}

function Row({ name, a, b, lowerIsBetter = false }: { name: string; a: RateOut; b: RateOut; lowerIsBetter?: boolean }) {
  const better = lowerIsBetter ? b.k < a.k : b.k > a.k
  const worse = lowerIsBetter ? b.k > a.k : b.k < a.k
  const bar = (rate: RateOut, color: string) => (
    <div className="h-2 flex-1 overflow-hidden rounded-full bg-white">
      <div
        className="animate-grow-x h-full rounded-full"
        style={{ width: `${Math.max(rate.rate ? 2 : 0, (rate.rate ?? 0) * 100)}%`, background: color }}
        title={pct(rate)}
      />
    </div>
  )
  return (
    <div>
      <div className="mb-1.5 flex items-baseline gap-2 text-sm">
        <span className="font-medium">{name}</span>
        <span className="ml-auto text-xs text-ink-3">{pct(a)}</span>
        <Icon name="arrowRight" size={12} className="text-ink-3" />
        <span className={`text-xs font-semibold ${better ? 'text-[#0b7a54]' : worse ? 'text-[#c42b36]' : 'text-ink'}`}>
          {pct(b)}
        </span>
      </div>
      <div className="flex flex-col gap-0.5">
        {bar(a, '#c3c6d1')}
        {bar(b, '#2a78d6')}
      </div>
    </div>
  )
}
