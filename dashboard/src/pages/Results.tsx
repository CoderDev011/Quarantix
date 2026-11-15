// F21 results: the last red-team report, per domain and mode, every rate with n and a 95% interval.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api } from '../api/client.ts'
import { Icon } from '../components/ui/Icon.tsx'
import { EmptyState, ErrorNote, IconDot, PageHeader, Skeleton } from '../components/ui/primitives.tsx'

type Rate = { k: number; n: number; rate: number | null; ci95: [number, number] }
type Metric = {
  domain: string
  mode: string
  asr_asks_denied: Rate
  asr_asks_approved?: Rate
  tsr: Rate
  false_block_rate: Rate
  approval_rate: Rate
  errors: number
}
// This endpoint returns the runner's JSON file as-is (contracts section 16), so it has no
// OpenAPI schema to generate from; these are the fields the page reads.
type Report = { run_id: string; date: string; source: string; models: Record<string, string>; metrics: Metric[] }

function fmt(rate: Rate | undefined) {
  if (!rate || rate.rate === null) return 'n/a'
  const [low, high] = rate.ci95
  return `${Math.round(rate.rate * 100)}% (${rate.k}/${rate.n}; ${Math.round(low * 100)}-${Math.round(high * 100)}%)`
}

const METRICS = [
  { key: 'asr_asks_denied', title: 'Attack success', note: 'asks denied · lower is better' },
  { key: 'tsr', title: 'Task success', note: 'benign tasks completed · higher is better' },
  { key: 'false_block_rate', title: 'False blocks', note: 'benign calls stopped · lower is better' },
] as const

export default function Results() {
  const report = useQuery({ queryKey: ['redteam'], queryFn: () => api<Report>('/v1/redteam/latest'), retry: false })
  const [metric, setMetric] = useState<(typeof METRICS)[number]['key']>('asr_asks_denied')
  const header = (
    <PageHeader
      eyebrow="Evidence"
      title="Red-team results"
      subtitle="The latest red-team run, per domain and mode. Every rate shows its sample size and a 95% interval."
    />
  )
  if (report.isPending) {
    return (
      <section className="flex flex-col gap-6">
        {header}
        <Skeleton className="h-24 rounded-4xl" />
        <Skeleton className="h-72 rounded-4xl" />
      </section>
    )
  }
  if (report.isError) {
    const missing = report.error instanceof ApiError && report.error.status === 404
    return (
      <section className="flex flex-col gap-6">
        {header}
        {missing ? (
          <div className="card">
            <EmptyState icon="chart" title="No report yet">
              Run <code className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-xs">uv run python scripts/redteam.py</code>
            </EmptyState>
          </div>
        ) : (
          <ErrorNote>{String(report.error)}</ErrorNote>
        )}
      </section>
    )
  }
  const data = report.data
  const domains = [...new Set(data.metrics.map((m) => m.domain))]
  const current = METRICS.find((m) => m.key === metric) ?? METRICS[0]
  return (
    <section className="flex flex-col gap-6">
      {header}
      <div className="animate-rise flex flex-wrap gap-3" style={{ animationDelay: '60ms' }}>
        <Meta icon="file" label="Run" value={data.run_id} />
        <Meta icon="activity" label="Date" value={data.date} />
        <Meta icon="database" label="Source" value={data.source} />
        <Meta icon="cpu" label="Models" value={Object.values(data.models).join(', ') || 'none (replay of recorded traces)'} />
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-full bg-surface p-1 shadow-soft">
          {METRICS.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => setMetric(m.key)}
              className={`rounded-full px-4 py-2 text-sm font-medium transition ${
                metric === m.key ? 'bg-ink text-white' : 'text-ink-3 hover:text-ink'
              }`}
            >
              {m.title}
            </button>
          ))}
        </div>
        <span className="text-xs text-ink-3">{current.note}</span>
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {domains.map((domain, i) => (
          <div key={domain} className="card animate-rise p-6" style={{ animationDelay: `${i * 90}ms` }}>
            <div className="mb-5 flex items-center gap-3">
              <IconDot icon="layers" tone={i % 2 ? 'sun' : 'tangerine'} />
              <div>
                <p className="font-semibold capitalize">{domain}</p>
                <p className="text-xs text-ink-3">
                  {current.title} by mode · bar = rate, whisker = 95% interval
                </p>
              </div>
            </div>
            <Bars rows={data.metrics.filter((m) => m.domain === domain)} metric={metric} key={metric} />
          </div>
        ))}
      </div>

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[860px] text-sm">
          <thead>
            <tr className="border-b border-line text-left text-xs text-ink-3">
              {['Domain', 'Mode', 'ASR (asks denied)', 'ASR (asks approved)', 'TSR', 'False blocks', 'Approval rate', 'Errors'].map((h) => (
                <th key={h} className="px-4 py-3 font-semibold first:pl-6">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.metrics.map((m) => (
              <tr key={`${m.domain}-${m.mode}`} className="border-b border-line/60 transition last:border-0 hover:bg-surface-2/60">
                <td className="px-4 py-3 pl-6 font-medium capitalize">{m.domain}</td>
                <td className="px-4 py-3">
                  <span className="chip">{m.mode}</span>
                </td>
                <td className="px-4 py-3 tabular">{fmt(m.asr_asks_denied)}</td>
                <td className="px-4 py-3 tabular">{fmt(m.asr_asks_approved)}</td>
                <td className="px-4 py-3 tabular">{fmt(m.tsr)}</td>
                <td className="px-4 py-3 tabular">{fmt(m.false_block_rate)}</td>
                <td className="px-4 py-3 tabular">{fmt(m.approval_rate)}</td>
                <td className="px-4 py-3 tabular">{m.errors}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="flex items-center gap-2 text-xs text-ink-3">
        <Icon name="alert" size={13} /> Replay runs re-issue recorded tool-call traces; scripted traces are hand-written,
        not a model run. Errors are counted but never scored.
      </p>
    </section>
  )
}

function Meta({ icon, label, value }: { icon: 'file' | 'activity' | 'database' | 'cpu'; label: string; value: string }) {
  return (
    <div className="flex min-w-0 max-w-full items-center gap-3 rounded-full bg-surface py-2 pr-5 pl-2 shadow-soft">
      <IconDot icon={icon} tone="neutral" size={36} />
      <div className="min-w-0 leading-tight">
        <p className="text-[11px] text-ink-3">{label}</p>
        <p className="truncate font-mono text-sm">{value}</p>
      </div>
    </div>
  )
}

/** One horizontal bar per mode: the rate, a 95% CI whisker, and the value printed at the end. */
function Bars({ rows, metric }: { rows: Metric[]; metric: (typeof METRICS)[number]['key'] }) {
  const [hover, setHover] = useState<string | null>(null)
  return (
    <div className="flex flex-col gap-4">
      {rows.map((row, i) => {
        const rate = row[metric]
        const value = rate.rate
        return (
          <div
            key={row.mode}
            className="group"
            onMouseEnter={() => setHover(row.mode)}
            onMouseLeave={() => setHover(null)}
          >
            <div className="mb-1.5 flex items-baseline justify-between text-sm">
              <span className="font-medium capitalize">{row.mode}</span>
              <span className="tabular text-ink-2">
                {value === null ? 'n/a' : `${Math.round(value * 100)}%`}
                <span className="ml-1.5 text-xs text-ink-3">
                  {rate.k}/{rate.n}
                </span>
              </span>
            </div>
            <div className="relative h-7 rounded-lg bg-surface-2">
              {value !== null && (
                <>
                  <div
                    className="animate-grow-x absolute inset-y-0 left-0 rounded-r-[4px] rounded-l-lg bg-[#2a78d6] transition-opacity"
                    style={{ width: `${Math.max(0.6, value * 100)}%`, animationDelay: `${i * 120}ms`, opacity: hover && hover !== row.mode ? 0.45 : 1 }}
                  />
                  <div
                    className="absolute top-1/2 h-[2px] -translate-y-1/2 bg-ink"
                    style={{ left: `${rate.ci95[0] * 100}%`, width: `${(rate.ci95[1] - rate.ci95[0]) * 100}%` }}
                  />
                  {rate.ci95.map((edge, j) => (
                    <div key={j} className="absolute top-1/2 h-3 w-[2px] -translate-y-1/2 bg-ink" style={{ left: `calc(${edge * 100}% - 1px)` }} />
                  ))}
                </>
              )}
              {hover === row.mode && (
                <div className="pointer-events-none absolute -top-10 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-full bg-ink px-3 py-1.5 text-xs text-white shadow-lift">
                  {row.mode}: {fmt(rate)}
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
