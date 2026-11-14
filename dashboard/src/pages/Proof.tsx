// F22 proof wall: every scenario, every mode, what was expected and what happened.
import { useQuery } from '@tanstack/react-query'
import { proof } from '../api/arena.ts'

const VERDICT: Record<string, string> = {
  pass: 'bg-emerald-600',
  partial: 'bg-amber-500 text-black',
  fail: 'bg-red-600',
}

export default function Proof() {
  const report = useQuery({ queryKey: ['proof'], queryFn: proof.run, staleTime: 60_000 })
  if (report.isPending) return <p className="text-slate-400">Running the proof suite…</p>
  if (report.isError) return <p className="text-red-400">{String(report.error)}</p>
  const data = report.data
  return (
    <section className="flex flex-col gap-4">
      <header className="flex items-baseline gap-4">
        <h1 className="text-2xl font-semibold">Real-World Proof Suite</h1>
        <span className="text-slate-400">
          {data.passed} passed · {data.partial} partial · {data.failed} failed · {data.total} scenarios
        </span>
        <button
          type="button"
          onClick={() => report.refetch()}
          className="ml-auto rounded bg-slate-800 px-3 py-1 text-sm"
        >
          Run again
        </button>
      </header>
      <table className="w-full text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            <th className="py-1 font-normal">Scenario</th>
            <th className="font-normal">Category</th>
            <th className="font-normal">Baseline</th>
            <th className="font-normal">Guard</th>
            <th className="font-normal">Full</th>
            <th className="font-normal">Verdict</th>
          </tr>
        </thead>
        <tbody>
          {data.scenarios.map((s) => (
            <tr key={s.scenario_id} className="border-t border-slate-800 align-top">
              <td className="py-2">
                <div className="font-medium">{s.scenario_id}</div>
                <div className="text-slate-400">{s.title}</div>
              </td>
              <td className="py-2 text-slate-400">{s.category.replace('_', ' ')}</td>
              {(['baseline', 'guard', 'full'] as const).map((mode) => {
                const m = s.modes[mode]
                if (!m) return <td key={mode} className="py-2 text-slate-600">–</td>
                const tone = m.outcome === 'skipped' ? 'text-slate-500' : m.passed ? 'text-emerald-300' : 'text-red-300'
                return (
                  <td key={mode} className={`py-2 ${tone}`} title={m.why ?? m.rule ?? ''}>
                    {m.outcome}
                    {m.rule && <div className="text-xs text-slate-500">{m.rule}</div>}
                    {m.why && <div className="text-xs text-slate-500">{m.why}</div>}
                  </td>
                )
              })}
              <td className="py-2">
                <span className={`rounded px-2 py-0.5 text-xs font-bold uppercase ${VERDICT[s.verdict]}`}>
                  {s.verdict}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="text-xs text-slate-500">
        Baseline and guard replay recorded tool-call traces; full mode runs only with a working reader and is
        shown as skipped otherwise, never as a pass.
      </p>
    </section>
  )
}
