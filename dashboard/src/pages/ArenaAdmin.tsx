// Arena moderation for the team: recent attempts (with payloads, admin only), hide, pause, booth reset.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { arena, OUTCOME_ICON } from '../api/arena.ts'

export default function ArenaAdmin() {
  const queryClient = useQueryClient()
  const attempts = useQuery({ queryKey: ['arena-admin'], queryFn: arena.adminAttempts, refetchInterval: 3000 })
  const stats = useQuery({ queryKey: ['arena', 'stats'], queryFn: arena.stats, refetchInterval: 3000 })
  const [clear, setClear] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['arena-admin'] })
  const hide = useMutation({ mutationFn: arena.hide, onSuccess: refresh })
  const pause = useMutation({
    mutationFn: () => (stats.data?.paused ? arena.resume() : arena.pause()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['arena', 'stats'] }),
  })
  const reset = useMutation({ mutationFn: () => arena.reset(clear), onSuccess: refresh })
  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold">Arena</h1>
        <span className="text-sm text-slate-400">
          {stats.data?.attempts ?? 0} attempts · queue {stats.data?.queue_depth ?? 0} ·{' '}
          {stats.data?.paused ? 'paused' : 'running'}
        </span>
        <a href="/arena/screen" target="_blank" rel="noreferrer" className="text-sm text-sky-400 underline">
          Open big screen
        </a>
        <button type="button" onClick={() => pause.mutate()} className="ml-auto rounded bg-slate-700 px-3 py-1 text-sm">
          {stats.data?.paused ? 'Resume' : 'Pause'}
        </button>
        <label className="flex items-center gap-1 text-sm text-slate-300">
          <input type="checkbox" checked={clear} onChange={(e) => setClear(e.target.checked)} /> also clear scores
        </label>
        <button
          type="button"
          onClick={() => reset.mutate()}
          className="rounded bg-red-700 px-3 py-1 text-sm font-semibold"
        >
          Booth reset
        </button>
      </header>
      {reset.data && (
        <p className="text-sm text-emerald-300">
          Reset in {reset.data.seconds}s: day-one policy restored for {reset.data.restored.join(', ')}; removed{' '}
          {reset.data.removed.length ? reset.data.removed.join(', ') : 'no Autopilot rules'}.
        </p>
      )}
      <table className="w-full text-sm">
        <thead className="text-left text-slate-400">
          <tr>
            <th className="font-normal">Player</th>
            <th className="font-normal">Mission</th>
            <th className="font-normal">Payload (team only)</th>
            <th className="font-normal">Naive · Guard · Full</th>
            <th className="font-normal" />
          </tr>
        </thead>
        <tbody>
          {(attempts.data?.attempts ?? []).map((a) => (
            <tr key={a.attempt_id} className={`border-t border-slate-800 align-top ${a.hidden ? 'opacity-40' : ''}`}>
              <td className="py-2">{a.nickname}</td>
              <td className="py-2 text-slate-300">
                {a.domain} · {a.goal_title}
              </td>
              <td className="max-w-md truncate py-2 font-mono text-xs text-slate-400" title={a.payload}>
                {a.payload}
              </td>
              <td className="py-2 text-lg">
                {[a.defenders.naive, a.defenders.guard, a.defenders.full]
                  .map((r) => (r ? OUTCOME_ICON[r.outcome] : '…'))
                  .join(' ')}
              </td>
              <td className="py-2">
                <button
                  type="button"
                  disabled={a.hidden}
                  onClick={() => hide.mutate({ attempt_id: a.attempt_id })}
                  className="mr-2 rounded bg-slate-700 px-2 text-xs disabled:opacity-30"
                >
                  Hide
                </button>
                <button
                  type="button"
                  onClick={() => hide.mutate({ player_id: a.player_id })}
                  className="rounded bg-slate-700 px-2 text-xs"
                >
                  Hide player
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
