// F22 proof wall: every scenario, every mode, what was expected and what happened.
import { useQuery } from '@tanstack/react-query'
import { proof } from '../api/arena.ts'
import { Icon, type IconName } from '../components/ui/Icon.tsx'
import { CountUp } from '../components/ui/motion.tsx'
import { ErrorNote, PageHeader, Pill, type PillTone, Skeleton } from '../components/ui/primitives.tsx'

// Status colors carry an icon and a label too, never color alone.
const VERDICT: Record<string, { tone: PillTone; icon: IconName; color: string; label: string }> = {
  pass: { tone: 'good', icon: 'check', color: '#1baf7a', label: 'Passed' },
  partial: { tone: 'warn', icon: 'alert', color: '#eda100', label: 'Partial' },
  fail: { tone: 'bad', icon: 'x', color: '#e34948', label: 'Failed' },
}

export default function Proof() {
  const report = useQuery({ queryKey: ['proof'], queryFn: proof.run, staleTime: 60_000 })
  const running = report.isFetching
  return (
    <section className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Evidence"
        title="Real-World Proof Suite"
        subtitle="Every scenario, every mode: what was expected and what actually happened."
        actions={
          <button type="button" disabled={running} onClick={() => report.refetch()} className="btn btn-ink">
            <Icon name="refresh" size={15} className={running ? 'animate-spin' : ''} />
            {running ? 'Running…' : 'Run again'}
          </button>
        }
      />
      {report.isPending && <Loading />}
      {report.isError && <ErrorNote>{String(report.error)}</ErrorNote>}
      {report.data && <Report data={report.data} />}
    </section>
  )
}

function Loading() {
  return (
    <div className="flex flex-col gap-4">
      <div className="card flex items-center gap-4 p-6">
        <span className="relative flex h-12 w-12">
          <span className="animate-ring-pulse absolute inset-0 rounded-full bg-brand/40" />
          <span className="relative flex h-12 w-12 items-center justify-center rounded-full bg-brand text-white">
            <Icon name="shieldCheck" size={22} />
          </span>
        </span>
        <div>
          <p className="font-semibold">Running the proof suite…</p>
          <p className="text-sm text-ink-3">Replaying each scenario against baseline, guard and full.</p>
        </div>
      </div>
      {[0, 1, 2, 3].map((i) => (
        <Skeleton key={i} className="h-20 rounded-3xl" />
      ))}
    </div>
  )
}

type ReportData = NonNullable<Awaited<ReturnType<typeof proof.run>>>

function Report({ data }: { data: ReportData }) {
  const parts = [
    { key: 'pass', value: data.passed },
    { key: 'partial', value: data.partial },
    { key: 'fail', value: data.failed },
  ].filter((p) => p.value > 0)
  return (
    <>
      <div className="animate-rise grid gap-4 lg:grid-cols-[1.4fr_1fr]" style={{ animationDelay: '60ms' }}>
        <div className="card p-6">
          <p className="eyebrow">Scenarios passed</p>
          <p className="mt-2 text-5xl font-semibold tracking-tight">
            <CountUp value={data.passed} duration={1200} />
            <span className="text-2xl text-ink-3"> / {data.total}</span>
          </p>
          <div className="mt-6 flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label={`${data.passed} passed, ${data.partial} partial, ${data.failed} failed of ${data.total}`}>
            {parts.map((p, i) => (
              <div
                key={p.key}
                className="animate-grow-x h-full first:rounded-l-full last:rounded-r-full"
                style={{ flexGrow: p.value, background: VERDICT[p.key].color, animationDelay: `${i * 150}ms` }}
                title={`${VERDICT[p.key].label}: ${p.value}`}
              />
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-4 text-sm">
            {(['pass', 'partial', 'fail'] as const).map((k) => (
              <span key={k} className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ background: VERDICT[k].color }} />
                <span className="text-ink-2">{VERDICT[k].label}</span>
                <span className="font-semibold">{k === 'pass' ? data.passed : k === 'partial' ? data.partial : data.failed}</span>
              </span>
            ))}
          </div>
        </div>
        <div className="card flex flex-col justify-center gap-3 bg-ink p-6 text-white">
          <Icon name="shieldCheck" size={28} className="text-mint" />
          <p className="text-[15px] leading-relaxed text-white/80">
            Baseline and guard replay recorded tool-call traces. Full mode runs only with a working reader, and is
            shown as <span className="font-semibold text-white">skipped</span> otherwise, never as a pass.
          </p>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_repeat(3,minmax(0,1fr))_7rem] gap-4 border-b border-line px-6 py-3 text-xs font-semibold text-ink-3 lg:grid">
          <span>Scenario</span>
          <span>Category</span>
          <span>Baseline</span>
          <span>Guard</span>
          <span>Full</span>
          <span>Verdict</span>
        </div>
        <ul>
          {data.scenarios.map((s, i) => {
            const v = VERDICT[s.verdict]
            return (
              <li
                key={s.scenario_id}
                className="animate-rise grid gap-3 border-b border-line/70 px-6 py-4 transition last:border-0 hover:bg-surface-2/60 lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1fr)_repeat(3,minmax(0,1fr))_7rem] lg:items-center lg:gap-4"
                style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
              >
                <div className="min-w-0">
                  <p className="font-mono text-xs text-ink-3">{s.scenario_id}</p>
                  <p className="font-medium">{s.title}</p>
                </div>
                <span className="chip w-fit">{s.category.replace('_', ' ')}</span>
                {(['baseline', 'guard', 'full'] as const).map((mode) => {
                  const m = s.modes[mode]
                  if (!m) return <span key={mode} className="text-ink-3">–</span>
                  const tone: PillTone = m.outcome === 'skipped' ? 'neutral' : m.passed ? 'good' : 'bad'
                  return (
                    <div key={mode} className="min-w-0" title={m.why ?? m.rule ?? ''}>
                      <span className="mr-2 text-xs text-ink-3 lg:hidden">{mode}</span>
                      <Pill tone={tone} icon={m.outcome === 'skipped' ? undefined : m.passed ? 'check' : 'x'}>
                        {m.outcome}
                      </Pill>
                      {m.rule && <p className="mt-1 truncate font-mono text-[11px] text-ink-3">{m.rule}</p>}
                      {m.why && <p className="mt-0.5 line-clamp-2 text-[11px] text-ink-3">{m.why}</p>}
                    </div>
                  )
                })}
                <Pill tone={v.tone} icon={v.icon} className="w-fit">
                  {s.verdict}
                </Pill>
              </li>
            )
          })}
        </ul>
      </div>
    </>
  )
}
