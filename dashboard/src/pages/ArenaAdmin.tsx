// Arena moderation for the team: recent attempts (with payloads, admin only), hide, pause, booth reset.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { arena, OUTCOME_ICON } from '../api/arena.ts'
import { Icon, type IconName } from '../components/ui/Icon.tsx'
import { CountUp } from '../components/ui/motion.tsx'
import { EmptyState, IconDot, PageHeader, Pill, Skeleton, Toggle, type Tone } from '../components/ui/primitives.tsx'

export default function ArenaAdmin() {
  const queryClient = useQueryClient()
  const attempts = useQuery({ queryKey: ['arena-admin'], queryFn: arena.adminAttempts, refetchInterval: 3000 })
  const stats = useQuery({ queryKey: ['arena', 'stats'], queryFn: arena.stats, refetchInterval: 3000 })
  const [clear, setClear] = useState(false)
  const [armed, setArmed] = useState(false)
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['arena-admin'] })
  const hide = useMutation({ mutationFn: arena.hide, onSuccess: refresh })
  const pause = useMutation({
    mutationFn: () => (stats.data?.paused ? arena.resume() : arena.pause()),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['arena', 'stats'] }),
  })
  const reset = useMutation({ mutationFn: () => arena.reset(clear), onSuccess: refresh })
  useEffect(() => {
    if (!armed) return
    const timer = setTimeout(() => setArmed(false), 4000)
    return () => clearTimeout(timer)
  }, [armed])
  const s = stats.data
  const paused = s?.paused ?? false
  const list = attempts.data?.attempts ?? []

  const categories: { icon: IconName; tone: Tone; label: string; value: number }[] = [
    { icon: 'target', tone: 'ink', label: 'Attempts', value: s?.attempts ?? 0 },
    { icon: 'activity', tone: 'sky', label: 'In queue', value: s?.queue_depth ?? 0 },
    { icon: 'flame', tone: 'rose', label: 'Naive breaches', value: s?.breaches.naive ?? 0 },
    { icon: 'alert', tone: 'sun', label: 'Gaps found', value: s?.breaches_found ?? 0 },
    { icon: 'shieldCheck', tone: 'mint', label: 'Gaps patched', value: s?.breaches_patched ?? 0 },
  ]

  return (
    <section className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Booth"
        title="Arena"
        subtitle="Moderate attempts, pause the queue, and reset the booth between sessions."
        actions={
          <a href="/arena/screen" target="_blank" rel="noreferrer" className="btn btn-ghost">
            <Icon name="monitor" size={15} /> Open big screen <Icon name="arrowUpRight" size={14} />
          </a>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        {categories.map((c, i) => (
          <div
            key={c.label}
            className="animate-rise relative rounded-3xl bg-surface p-4 shadow-soft transition duration-300 hover:-translate-y-0.5 hover:shadow-lift"
            style={{ animationDelay: `${i * 60}ms` }}
          >
            <IconDot icon={c.icon} tone={c.tone} />
            <p className="mt-6 text-2xl font-semibold">
              <CountUp value={c.value} />
            </p>
            <p className="text-xs text-ink-3">{c.label}</p>
          </div>
        ))}
      </div>

      <div className="card flex flex-wrap items-center gap-4 p-5">
        <div className="flex items-center gap-3">
          <IconDot icon={paused ? 'pause' : 'play'} tone={paused ? 'amber' : 'mint'} />
          <div>
            <p className="font-semibold">{paused ? 'Queue paused' : 'Queue running'}</p>
            <p className="text-xs text-ink-3">{paused ? 'New attacks wait until you resume.' : 'Attacks run as they arrive.'}</p>
          </div>
          <Toggle on={!paused} onChange={() => pause.mutate()} label="Queue running" disabled={!s || pause.isPending} />
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-ink-2">
            <Toggle on={clear} onChange={setClear} label="Also clear scores" />
            Also clear scores
          </label>
          <button
            type="button"
            disabled={reset.isPending}
            onClick={() => {
              if (!armed) return setArmed(true)
              setArmed(false)
              reset.mutate()
            }}
            className={`btn btn-danger ${armed ? 'animate-pulse' : ''}`}
          >
            <Icon name="refresh" size={15} className={reset.isPending ? 'animate-spin' : ''} />
            {reset.isPending ? 'Resetting…' : armed ? 'Click again to reset' : 'Booth reset'}
          </button>
        </div>
      </div>
      {reset.data && (
        <p className="animate-rise flex items-start gap-2 rounded-3xl bg-mint/12 px-5 py-4 text-sm text-[#0b6a49]">
          <Icon name="check" size={16} className="mt-0.5 shrink-0" />
          Reset in {reset.data.seconds}s: day-one policy restored for {reset.data.restored.join(', ')}; removed{' '}
          {reset.data.removed.length ? reset.data.removed.join(', ') : 'no Autopilot rules'}.
        </p>
      )}

      <div>
        <div className="mb-3 flex items-center gap-3">
          <h2 className="text-lg font-semibold">Recent attempts</h2>
          <span className="text-xs text-ink-3">payloads are visible to the team only · naive · guard · full</span>
        </div>
        {attempts.isPending && <Skeleton className="h-48 rounded-4xl" />}
        {!attempts.isPending && list.length === 0 && (
          <div className="card">
            <EmptyState icon="target" title="No attempts yet">
              Attacks from phones and the Red Agent show up here.
            </EmptyState>
          </div>
        )}
        <ul className="flex flex-col gap-2">
          {list.map((a) => (
            <li
              key={a.attempt_id}
              className={`grid items-center gap-3 rounded-3xl bg-surface p-3 pl-4 shadow-soft transition md:grid-cols-[12rem_minmax(0,14rem)_minmax(0,1fr)_auto_auto] ${
                a.hidden ? 'opacity-45' : ''
              }`}
            >
              <div className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-lilac to-sky text-xs font-bold text-white uppercase">
                  {a.nickname.slice(0, 2)}
                </span>
                <span className="truncate font-medium">{a.nickname}</span>
                {a.hidden && <Pill>hidden</Pill>}
              </div>
              <div className="min-w-0 text-sm">
                <p className="truncate">{a.goal_title}</p>
                <p className="text-xs text-ink-3">{a.domain}</p>
              </div>
              <p className="truncate rounded-2xl bg-surface-2 px-3 py-2 font-mono text-xs text-ink-2" title={a.payload}>
                {a.payload}
              </p>
              <span className="flex gap-1.5 text-xl" title="naive · guard · full">
                {[a.defenders.naive, a.defenders.guard, a.defenders.full].map((r, i) => (
                  <span key={i} className="flex h-9 w-9 items-center justify-center rounded-full bg-surface-2">
                    {r ? OUTCOME_ICON[r.outcome] : '…'}
                  </span>
                ))}
              </span>
              <div className="flex gap-1.5">
                <button
                  type="button"
                  disabled={a.hidden}
                  onClick={() => hide.mutate({ attempt_id: a.attempt_id })}
                  className="btn btn-soft px-3 py-1.5 text-xs"
                >
                  <Icon name="eyeOff" size={13} /> Hide
                </button>
                <button
                  type="button"
                  onClick={() => hide.mutate({ player_id: a.player_id })}
                  className="btn btn-soft px-3 py-1.5 text-xs"
                >
                  <Icon name="user" size={13} /> Hide player
                </button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
