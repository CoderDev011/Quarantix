// Small visual building blocks shared by the console and (later) the arena.
import type { ArgPreviewOut, DecisionOut, EventOut } from '../api/client.ts'

const CONFIDENTIALITY_TAG: Record<string, string> = {
  public: 'pub',
  internal: 'int',
  private: 'priv',
  secret: 'SECRET',
}

/** One argument: its preview plus who could have written it (green trusted, red untrusted). */
export function ArgChip({ name, arg }: { name: string; arg: ArgPreviewOut }) {
  const untrusted = arg.label?.integrity === 'untrusted'
  const inferred = arg.evidence === 'inferred'
  const color = untrusted
    ? 'border-red-500/70 bg-red-500/10 text-red-200'
    : 'border-emerald-500/60 bg-emerald-500/10 text-emerald-200'
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 rounded border px-1.5 py-0.5 text-xs ${color} ${inferred ? 'border-dashed' : ''}`}
      title={`${untrusted ? 'untrusted' : 'trusted'}${arg.evidence ? ` · evidence: ${arg.evidence}` : ''}`}
    >
      <span className="font-medium">{name}</span>
      <span className="truncate text-slate-300">{arg.preview}</span>
      {arg.label && (
        <span className="rounded bg-slate-800 px-1 text-[10px] uppercase text-slate-400">
          {CONFIDENTIALITY_TAG[arg.label.confidentiality]}
        </span>
      )}
    </span>
  )
}

type Verdict = { text: string; className: string }

export function verdictOf(event: EventOut): Verdict {
  const decision: DecisionOut | null | undefined = event.decision
  if (event.outcome === 'blocked') return { text: 'BLOCKED', className: 'bg-red-600 text-white' }
  if (decision && !decision.enforced && decision.kind !== 'allow')
    return { text: decision.kind === 'block' ? 'WOULD BLOCK' : 'WOULD ASK', className: 'bg-amber-500 text-black' }
  if (decision?.kind === 'ask') return { text: 'APPROVED', className: 'bg-sky-600 text-white' }
  if (event.outcome === 'error') return { text: 'ERROR', className: 'bg-slate-500 text-white' }
  return { text: 'ALLOWED', className: 'bg-emerald-700 text-white' }
}

export function VerdictBadge({ event }: { event: EventOut }) {
  const { text, className } = verdictOf(event)
  return <span className={`rounded px-1.5 py-0.5 text-[11px] font-bold tracking-wide ${className}`}>{text}</span>
}
