// F18 console: proposals with their rule, rationale and proof; Enable only when the proof passed.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { autopilot, type ProposalOut, type RateOut } from '../api/arena.ts'
import { ApiError } from '../api/client.ts'

const STATUS_STYLE: Record<ProposalOut['status'], string> = {
  drafted: 'bg-slate-700',
  proving: 'bg-sky-700',
  proved_pass: 'bg-emerald-700',
  proved_fail: 'bg-red-700',
  enabled: 'bg-emerald-500 text-black',
  rejected: 'bg-slate-600',
  rolled_back: 'bg-amber-600 text-black',
}

export default function Autopilot() {
  const queryClient = useQueryClient()
  const proposals = useQuery({ queryKey: ['proposals'], queryFn: autopilot.proposals, refetchInterval: 2000 })
  const settings = useQuery({ queryKey: ['autopilot-settings'], queryFn: autopilot.settings })
  const toggle = useMutation({
    mutationFn: (on: boolean) => autopilot.setAutonomous(on),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['autopilot-settings'] }),
  })
  const items = proposals.data?.proposals ?? []
  return (
    <section className="flex flex-col gap-4">
      <header className="flex items-center gap-4">
        <h1 className="text-2xl font-semibold">Policy Autopilot</h1>
        <label className="ml-auto flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={settings.data?.autonomous ?? false}
            onChange={(e) => toggle.mutate(e.target.checked)}
          />
          Autonomous (tighten-only rules that pass their proof are enabled, then watched by a canary)
        </label>
      </header>
      {items.length === 0 && (
        <p className="text-slate-400">
          No proposals yet. A breach of Guard or Full in the arena starts one automatically.
        </p>
      )}
      {items.map((p) => (
        <ProposalCard key={p.proposal_id} proposal={p} />
      ))}
    </section>
  )
}

function ProposalCard({ proposal: p }: { proposal: ProposalOut }) {
  const queryClient = useQueryClient()
  const act = useMutation({
    mutationFn: (action: 'enable' | 'reject' | 'rollback') => autopilot[action](p.proposal_id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['proposals'] }),
  })
  const proof = p.proof
  return (
    <article className="rounded-lg border border-slate-800 p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${STATUS_STYLE[p.status]}`}>
          {p.status.replace('_', ' ')}
        </span>
        <span className="font-medium">
          {p.domain} · {p.agent}
        </span>
        <span className="text-sm text-slate-400">
          trigger {p.trigger} · drafted by {p.draft_source}
          {p.seconds_to_patch !== null && p.seconds_to_patch !== undefined && ` · patched in ${p.seconds_to_patch}s`}
          {p.enabled_by && ` · enabled by ${p.enabled_by}`}
        </span>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            disabled={p.status !== 'proved_pass' || act.isPending}
            onClick={() => act.mutate('enable')}
            className="rounded bg-emerald-600 px-3 py-1 text-sm font-semibold disabled:opacity-30"
          >
            Enable
          </button>
          <button
            type="button"
            disabled={!['proved_pass', 'proved_fail', 'drafted'].includes(p.status) || act.isPending}
            onClick={() => act.mutate('reject')}
            className="rounded bg-slate-700 px-3 py-1 text-sm disabled:opacity-30"
          >
            Reject
          </button>
          <button
            type="button"
            disabled={p.status !== 'enabled' || act.isPending}
            onClick={() => act.mutate('rollback')}
            className="rounded bg-amber-600 px-3 py-1 text-sm text-black disabled:opacity-30"
          >
            Roll back
          </button>
        </div>
      </div>
      {act.error && (
        <p className="mt-2 text-sm text-red-400">
          {act.error instanceof ApiError ? act.error.message : String(act.error)}
        </p>
      )}
      <p className="mt-3 text-slate-200">{p.rationale}</p>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div>
          <h3 className="mb-1 text-sm uppercase tracking-wide text-slate-400">Rule (built by code from a template)</h3>
          <ul className="mb-2 text-sm">
            {p.candidate_rules.map((rule, i) => (
              <li key={i}>
                <code className="text-sky-300">{rule.template}</code>{' '}
                <span className="text-slate-400">{JSON.stringify(rule.parameters)}</span>
              </li>
            ))}
          </ul>
          <pre className="max-h-60 overflow-auto rounded bg-slate-900 p-3 text-xs text-emerald-200">{p.pack_yaml}</pre>
        </div>
        <div>
          <h3 className="mb-1 text-sm uppercase tracking-wide text-slate-400">
            Proof {proof ? `· ${proof.verdict.toUpperCase()} · ${proof.cases} cases · ${proof.seconds}s` : '· running'}
          </h3>
          {proof?.before && proof.after && (
            <table className="w-full text-sm">
              <thead className="text-slate-400">
                <tr>
                  <th className="text-left font-normal" />
                  <th className="text-left font-normal">Before</th>
                  <th className="text-left font-normal">After</th>
                </tr>
              </thead>
              <tbody>
                <Row name="Attack success" a={proof.before.asr} b={proof.after.asr} lowerIsBetter />
                <Row name="Task success" a={proof.before.tsr} b={proof.after.tsr} />
                <Row name="False blocks" a={proof.before.false_block_rate} b={proof.after.false_block_rate} lowerIsBetter />
                <Row name="Approval rate" a={proof.before.approval_rate} b={proof.after.approval_rate} lowerIsBetter />
              </tbody>
            </table>
          )}
          {proof?.trigger && (
            <p className="mt-2 text-sm">
              Trigger {proof.trigger.attempt_id}: {proof.trigger.before} → <b>{proof.trigger.after}</b>{' '}
              {proof.trigger.stopped ? '✔ stopped' : '✘ not stopped'}
            </p>
          )}
          {proof?.reasons && proof.reasons.length > 0 && (
            <ul className="mt-2 text-sm text-red-300">
              {proof.reasons.map((r) => (
                <li key={r}>✘ {r}</li>
              ))}
            </ul>
          )}
          {proof && (
            <p className="mt-2 text-xs text-slate-500">
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

function pct(rate: RateOut): string {
  return rate.rate === null || rate.rate === undefined ? 'n/a' : `${Math.round(rate.rate * 100)}% (${rate.k}/${rate.n})`
}

function Row({ name, a, b, lowerIsBetter = false }: { name: string; a: RateOut; b: RateOut; lowerIsBetter?: boolean }) {
  const better = (lowerIsBetter ? b.k < a.k : b.k > a.k) && 'text-emerald-300'
  const worse = (lowerIsBetter ? b.k > a.k : b.k < a.k) && 'text-red-300'
  return (
    <tr>
      <td className="text-slate-400">{name}</td>
      <td>{pct(a)}</td>
      <td className={better || worse || ''}>{pct(b)}</td>
    </tr>
  )
}
