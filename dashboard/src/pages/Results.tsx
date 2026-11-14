// F21 results: the last red-team report, per domain and mode, every rate with n and a 95% interval.
import { useQuery } from '@tanstack/react-query'
import { ApiError, api } from '../api/client.ts'

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

export default function Results() {
  const report = useQuery({ queryKey: ['redteam'], queryFn: () => api<Report>('/v1/redteam/latest'), retry: false })
  if (report.isPending) return <p className="text-slate-400">Loading…</p>
  if (report.isError) {
    const missing = report.error instanceof ApiError && report.error.status === 404
    return (
      <p className="text-slate-400">
        {missing ? 'No report yet. Run: uv run python scripts/redteam.py' : String(report.error)}
      </p>
    )
  }
  const data = report.data
  return (
    <section className="flex flex-col gap-3">
      <h1 className="text-2xl font-semibold">Red-team results</h1>
      <p className="text-sm text-slate-400">
        Run {data.run_id} · {data.date} · source: {data.source} · models:{' '}
        {Object.values(data.models).join(', ') || 'none (replay of recorded traces)'}
      </p>
      <table className="w-full text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            {['Domain', 'Mode', 'ASR (asks denied)', 'ASR (asks approved)', 'TSR', 'False blocks', 'Approval rate', 'Errors'].map(
              (h) => (
                <th key={h} className="py-1 font-normal">
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {data.metrics.map((m) => (
            <tr key={`${m.domain}-${m.mode}`} className="border-t border-slate-800">
              <td className="py-2">{m.domain}</td>
              <td>{m.mode}</td>
              <td>{fmt(m.asr_asks_denied)}</td>
              <td>{fmt(m.asr_asks_approved)}</td>
              <td>{fmt(m.tsr)}</td>
              <td>{fmt(m.false_block_rate)}</td>
              <td>{fmt(m.approval_rate)}</td>
              <td>{m.errors}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-500">
        Replay runs re-issue recorded tool-call traces; scripted traces are hand-written, not a model run.
        Errors are counted but never scored.
      </p>
    </section>
  )
}
