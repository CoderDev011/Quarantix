// F16 big screen: QR + counters (left), live ticker (center), leaderboard (right), breach alarm.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { arena, type AttemptOut, type AutopilotProgressOut, OUTCOME_ICON } from '../api/arena.ts'
import { BRAND } from '../brand.ts'
import { QrCode } from '../components/QrCode.tsx'
import { useArenaStream } from '../hooks/useArenaStream.ts'

const ALARM_MS = 60_000
const STEPS: { status: string; label: string }[] = [
  { status: 'drafted', label: 'Drafting a rule' },
  { status: 'proving', label: 'Proving it against every attack and task' },
  { status: 'proved_pass', label: 'Proof passed: ready for review' },
  { status: 'enabled', label: 'Patched' },
]

export default function ArenaScreen() {
  const feed = useArenaStream()
  const leaderboard = useQuery({
    queryKey: ['arena', 'leaderboard', feed.lastResult?.attempt_id],
    queryFn: arena.leaderboard,
    refetchInterval: 5000,
  })
  const initial = useQuery({ queryKey: ['arena', 'stats'], queryFn: arena.stats })
  const stats = feed.stats ?? initial.data ?? null
  const phoneUrl = `${(stats?.public_url || window.location.origin).replace(/\/$/, '')}/arena`
  const alarm = useBreachAlarm(feed.lastResult, feed.autopilot)

  return (
    <div className="relative grid h-screen grid-cols-[minmax(0,26rem)_minmax(0,1fr)_minmax(0,24rem)] gap-8 overflow-hidden bg-slate-950 p-8 text-slate-100">
      {!feed.connected && (
        <span className="absolute right-3 top-3 h-3 w-3 rounded-full bg-amber-400" title="reconnecting" />
      )}
      <section className="flex flex-col gap-6">
        <h1 className="text-4xl font-black tracking-tight">
          Break the <span className="text-red-500">Wall</span>
        </h1>
        <QrCode text={phoneUrl} size={340} />
        <p className="break-all text-lg text-slate-400">{phoneUrl}</p>
        <Counter label="Attacks launched" value={stats?.attempts ?? 0} />
        <Counter label="Naive agent breaches" value={stats?.breaches.naive ?? 0} tone="text-red-400" />
        <Counter label="Breaches found" value={stats?.breaches_found ?? 0} tone="text-amber-300" />
        <Counter label="Breaches patched" value={stats?.breaches_patched ?? 0} tone="text-emerald-400" />
        <p className="mt-auto text-base text-slate-500">
          Baseline model: {stats?.baseline_model ?? 'n/a'}
          {stats?.economy && <span className="ml-2 rounded bg-amber-500 px-2 text-black">economy mode</span>}
        </p>
      </section>

      <section className="flex min-h-0 flex-col">
        <h2 className="mb-4 text-2xl font-semibold text-slate-300">Latest attacks</h2>
        <ol className="flex flex-col gap-3">
          {Array.from({ length: 12 }, (_, i) => feed.ticker[i]).map((attempt, i) => (
            <TickerRow key={attempt?.attempt_id ?? `empty-${i}`} attempt={attempt} />
          ))}
        </ol>
      </section>

      <section>
        <h2 className="mb-4 text-2xl font-semibold text-slate-300">Leaderboard</h2>
        <ol className="flex flex-col gap-2">
          {(leaderboard.data?.leaderboard ?? []).slice(0, 10).map((row) => (
            <li key={row.rank} className="flex items-center gap-3 rounded-lg bg-slate-900 px-4 py-3 text-xl">
              <span className="w-8 text-slate-500">{row.rank}</span>
              <span className="flex-1 truncate font-semibold">{row.nickname}</span>
              <span className="tabular-nums text-emerald-300">{row.points.toLocaleString()}</span>
            </li>
          ))}
        </ol>
      </section>

      {alarm && <BreachAlarm nickname={alarm.nickname} progress={feed.autopilot} />}
    </div>
  )
}

function Counter({ label, value, tone = 'text-slate-100' }: { label: string; value: number; tone?: string }) {
  return (
    <div>
      <div className={`text-5xl font-black tabular-nums ${tone}`}>{value.toLocaleString()}</div>
      <div className="text-lg uppercase tracking-wide text-slate-400">{label}</div>
    </div>
  )
}

function TickerRow({ attempt }: { attempt: AttemptOut | undefined }) {
  if (!attempt) return <li className="h-14 rounded-lg bg-slate-900/40" />
  const d = attempt.defenders
  return (
    <li className="flex h-14 items-center gap-4 rounded-lg bg-slate-900 px-4 text-xl">
      <span className="w-48 truncate font-semibold">
        {attempt.source === 'red_agent' && <span title="Red Agent">🤖 </span>}
        {attempt.nickname}
      </span>
      <span className="flex-1 truncate text-slate-300">{attempt.goal_title}</span>
      <span className="hidden gap-1 text-sm text-slate-400 xl:flex">
        {attempt.technique_tags.slice(0, 2).map((t) => (
          <span key={t} className="rounded bg-slate-800 px-2">
            {t}
          </span>
        ))}
      </span>
      <span className="flex gap-3 text-2xl" title="naive · guard · full">
        {[d.naive, d.guard, d.full].map((r, i) => (
          <span key={i} className={r?.evaluation === 'shadow' && attempt.pending_rerun ? 'opacity-60' : ''}>
            {r ? OUTCOME_ICON[r.outcome] : '…'}
          </span>
        ))}
      </span>
    </li>
  )
}

/** A guard or full breach starts the alarm; it ends when patched or after 60 s. */
function useBreachAlarm(last: AttemptOut | null, progress: AutopilotProgressOut | null) {
  const [alarm, setAlarm] = useState<{ nickname: string; attemptId: string; since: number } | null>(null)
  useEffect(() => {
    if (!last) return
    const guard = last.defenders.guard?.outcome === 'breached'
    const full = last.defenders.full?.outcome === 'breached'
    if ((guard || full) && last.attempt_id !== alarm?.attemptId) {
      setAlarm({ nickname: last.nickname, attemptId: last.attempt_id, since: Date.now() })
    }
  }, [last, alarm?.attemptId])
  useEffect(() => {
    if (!alarm) return
    const done = progress?.status === 'enabled' && progress.attempt_ids.includes(alarm.attemptId)
    const timer = setTimeout(() => setAlarm(null), done ? 8000 : ALARM_MS - (Date.now() - alarm.since))
    return () => clearTimeout(timer)
  }, [alarm, progress])
  return alarm
}

function BreachAlarm({ nickname, progress }: { nickname: string; progress: AutopilotProgressOut | null }) {
  const reached = STEPS.findIndex((s) => s.status === progress?.status)
  const patched = progress?.status === 'enabled'
  const seconds = progress?.seconds_to_patch ?? null
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-10 bg-red-950/95">
      <div className={`text-7xl font-black ${patched ? 'text-emerald-300' : 'animate-pulse text-red-400'}`}>
        {patched ? 'Gap closed' : 'Breach found'}
      </div>
      <div className="text-4xl text-red-100">by {nickname}</div>
      <ol className="flex flex-col gap-4 text-3xl">
        {STEPS.map((step, i) => (
          <li key={step.status} className={i <= reached ? 'text-white' : 'text-red-300/50'}>
            {i <= reached ? '✔' : '○'} {step.label}
            {step.status === 'proving' && progress?.cases ? ` (${progress.cases} cases)` : ''}
            {step.status === 'enabled' && patched && seconds !== null
              ? ` in ${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`
              : ''}
          </li>
        ))}
      </ol>
      {progress?.status === 'proved_fail' && (
        <p className="text-2xl text-amber-300">The first rule failed its proof, so it was not enabled.</p>
      )}
      <p className="text-xl text-red-200/70">{BRAND} Autopilot never ships a rule without proof.</p>
    </div>
  )
}
