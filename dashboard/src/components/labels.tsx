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
  const color = untrusted ? 'border-rose/45 bg-rose/8 text-[#a3222c]' : 'border-mint/45 bg-mint/8 text-[#0b6a49]'
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${color} ${inferred ? 'border-dashed' : ''}`}
      title={`${untrusted ? 'untrusted' : 'trusted'}${arg.evidence ? ` · evidence: ${arg.evidence}` : ''}`}
    >
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${untrusted ? 'bg-rose' : 'bg-mint'}`} />
      <span className="font-semibold">{name}</span>
      <span className="truncate font-mono text-[11px] text-ink-2">{arg.preview}</span>
      {arg.label && (
        <span className="rounded-full bg-white px-1.5 text-[10px] font-semibold uppercase text-ink-3">
          {CONFIDENTIALITY_TAG[arg.label.confidentiality]}
        </span>
      )}
    </span>
  )
}

type Verdict = { text: string; className: string }

export function verdictOf(event: EventOut): Verdict {
  const decision: DecisionOut | null | undefined = event.decision
  if (event.outcome === 'blocked') return { text: 'Blocked', className: 'bg-rose text-white' }
  if (decision && !decision.enforced && decision.kind !== 'allow')
    return { text: decision.kind === 'block' ? 'Would block' : 'Would ask', className: 'bg-amber text-ink' }
  if (decision?.kind === 'ask') return { text: 'Approved', className: 'bg-sky text-white' }
  if (event.outcome === 'error') return { text: 'Error', className: 'bg-ink-3 text-white' }
  return { text: 'Allowed', className: 'bg-mint/15 text-[#0b7a54]' }
}

export function VerdictBadge({ event }: { event: EventOut }) {
  const { text, className } = verdictOf(event)
  return <span className={`whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-semibold ${className}`}>{text}</span>
}
