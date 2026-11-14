// F16 big screen: QR + counters (left), live ticker (center), leaderboard (right), breach alarm.
// Dark, high contrast, readable from 10 m. Animations are CSS transforms/opacity only (60 fps).
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { arena, type AttemptOut, type AutopilotProgressOut, type DefenderOut, OUTCOME_ICON } from '../api/arena.ts'
import { BRAND } from '../brand.ts'
import { QrCode } from '../components/QrCode.tsx'
import { Icon } from '../components/ui/Icon.tsx'
import { LogoMark } from '../components/ui/Logo.tsx'
import { CountUp } from '../components/ui/motion.tsx'
import { useArenaStream } from '../hooks/useArenaStream.ts'

const ALARM_MS = 60_000
const STEPS: { status: string; label: string }[] = [
  { status: 'drafted', label: 'Drafting a rule' },
  { status: 'proving', label: 'Proving it against every attack and task' },
  { status: 'proved_pass', label: 'Proof passed: ready for review' },
  { status: 'enabled', label: 'Patched' },
]

const OUTCOME_RING: Record<DefenderOut['outcome'], string> = {
  breached: 'bg-[#ff5a64]/20 ring-[#ff5a64]/60',
  blocked: 'bg-[#22c58b]/15 ring-[#22c58b]/50',
  neutralized: 'bg-white/8 ring-white/25',
  needs_approval: 'bg-[#59b4ff]/15 ring-[#59b4ff]/50',
  error: 'bg-[#f5a524]/15 ring-[#f5a524]/50',
}

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
    <div className="relative h-screen overflow-hidden bg-[#07070b] text-white [color-scheme:dark]">
      {/* Ambient background */}
      <div className="pointer-events-none absolute inset-0">
        <div className="animate-aurora absolute -top-40 left-1/4 h-[640px] w-[640px] rounded-full bg-[#6d5dfc]/25 blur-[140px]" />
        <div className="animate-aurora absolute -right-40 bottom-[-200px] h-[600px] w-[600px] rounded-full bg-[#ff7a1a]/15 blur-[140px]" style={{ animationDelay: '-9s' }} />
        <div className="absolute inset-0 bg-[radial-gradient(rgb(255_255_255/0.06)_1px,transparent_1px)] [background-size:28px_28px] [mask-image:radial-gradient(ellipse_at_center,#000_30%,transparent_75%)]" />
      </div>

      {!feed.connected && (
        <span className="absolute top-4 right-4 z-20 flex items-center gap-2 rounded-full bg-[#f5a524]/15 px-3 py-1.5 text-sm text-[#f5a524]" title="reconnecting">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[#f5a524]" /> reconnecting
        </span>
      )}

      <div className="relative grid h-full grid-cols-[minmax(0,26rem)_minmax(0,1fr)_minmax(0,24rem)] gap-8 p-8">
        <section className="flex min-h-0 flex-col gap-6">
          <div className="flex items-center gap-3">
            <LogoMark size={44} />
            <span className="text-lg font-medium text-white/60">{BRAND} Arena</span>
          </div>
          <h1 className="text-[3.4rem] font-semibold leading-[0.95] tracking-[-0.04em]">
            Break the{' '}
            <span className="bg-gradient-to-r from-[#ff5a64] to-[#ff7a1a] bg-clip-text text-transparent">Wall</span>
          </h1>
          <div className="beam self-start rounded-[28px] bg-white p-4 shadow-[0_0_80px_-10px_rgb(109_93_252/0.6)]">
            <QrCode text={phoneUrl} size={300} />
          </div>
          <p className="break-all font-mono text-base text-white/50">{phoneUrl}</p>
          <div className="grid grid-cols-2 gap-3">
            <Counter label="Attacks launched" value={stats?.attempts ?? 0} tone="text-white" />
            <Counter label="Naive breaches" value={stats?.breaches.naive ?? 0} tone="text-[#ff6b74]" />
            <Counter label="Breaches found" value={stats?.breaches_found ?? 0} tone="text-[#f7d23e]" />
            <Counter label="Breaches patched" value={stats?.breaches_patched ?? 0} tone="text-[#3ee0a1]" />
          </div>
          <p className="mt-auto flex items-center gap-2 text-base text-white/45">
            <Icon name="cpu" size={18} /> Baseline model: {stats?.baseline_model ?? 'n/a'}
            {stats?.economy && <span className="ml-2 rounded-full bg-[#f5a524] px-2.5 py-0.5 text-sm font-semibold text-black">economy mode</span>}
          </p>
        </section>

        <section className="flex min-h-0 flex-col">
          <h2 className="mb-4 flex items-center gap-3 text-2xl font-semibold text-white/80">
            <span className="relative flex h-3 w-3">
              <span className="animate-ring-pulse absolute inset-0 rounded-full bg-[#ff5a64]" />
              <span className="relative h-3 w-3 rounded-full bg-[#ff5a64]" />
            </span>
            Latest attacks
            <span className="ml-auto flex gap-6 pr-4 text-sm font-medium uppercase tracking-widest text-white/35">
              <span>naive</span>
              <span>guard</span>
              <span>full</span>
            </span>
          </h2>
          <ol className="flex flex-col gap-3">
            {Array.from({ length: 12 }, (_, i) => feed.ticker[i]).map((attempt, i) => (
              <TickerRow key={attempt?.attempt_id ?? `empty-${i}`} attempt={attempt} fresh={i === 0} />
            ))}
          </ol>
        </section>

        <section className="flex min-h-0 flex-col">
          <h2 className="mb-4 flex items-center gap-3 text-2xl font-semibold text-white/80">
            <Icon name="trophy" size={24} className="text-[#f7d23e]" /> Leaderboard
          </h2>
          <ol className="flex flex-col gap-2">
            {(leaderboard.data?.leaderboard ?? []).slice(0, 10).map((row) => (
              <li
                key={row.rank}
                className={`flex items-center gap-3 rounded-2xl px-4 py-3 text-xl ring-1 transition-all duration-500 ${
                  row.rank === 1
                    ? 'bg-gradient-to-r from-[#f7d23e]/25 to-transparent ring-[#f7d23e]/40'
                    : 'bg-white/[0.04] ring-white/[0.06]'
                }`}
              >
                <span
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-base font-bold ${
                    row.rank === 1
                      ? 'bg-[#f7d23e] text-black'
                      : row.rank === 2
                        ? 'bg-[#d8dbe5] text-black'
                        : row.rank === 3
                          ? 'bg-[#e0915a] text-black'
                          : 'bg-white/8 text-white/50'
                  }`}
                >
                  {row.rank}
                </span>
                <span className="flex-1 truncate font-semibold">{row.nickname}</span>
                <span className="tabular text-[#3ee0a1]">{row.points.toLocaleString()}</span>
              </li>
            ))}
            {(leaderboard.data?.leaderboard ?? []).length === 0 && (
              <li className="rounded-2xl bg-white/[0.04] px-4 py-6 text-center text-lg text-white/40">Be the first on the board.</li>
            )}
          </ol>
        </section>
      </div>

      {alarm && <BreachAlarm key={alarm.attemptId} nickname={alarm.nickname} progress={feed.autopilot} />}
    </div>
  )
}

function Counter({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div className="rounded-3xl bg-white/[0.05] p-4 ring-1 ring-white/[0.08] backdrop-blur">
      <div className={`text-5xl font-semibold tracking-tight ${tone}`}>
        <CountUp value={value} />
      </div>
      <div className="mt-1 text-sm uppercase tracking-wide text-white/45">{label}</div>
    </div>
  )
}

function TickerRow({ attempt, fresh }: { attempt: AttemptOut | undefined; fresh: boolean }) {
  if (!attempt) return <li className="h-14 rounded-2xl border border-dashed border-white/[0.07]" />
  const d = attempt.defenders
  const breach = d.guard?.outcome === 'breached' || d.full?.outcome === 'breached'
  return (
    <li
      className={`animate-rise flex h-14 items-center gap-4 rounded-2xl px-4 text-xl ring-1 ${
        breach ? 'bg-[#ff5a64]/12 ring-[#ff5a64]/40' : fresh ? 'bg-white/[0.08] ring-white/15' : 'bg-white/[0.04] ring-white/[0.06]'
      }`}
    >
      <span className="w-48 truncate font-semibold">
        {attempt.source === 'red_agent' && (
          <span title="Red Agent" className="mr-1.5 rounded-md bg-[#ff5a64]/20 px-1.5 py-0.5 text-base">
            🤖
          </span>
        )}
        {attempt.nickname}
      </span>
      <span className="flex-1 truncate text-white/70">{attempt.goal_title}</span>
      <span className="hidden gap-1.5 text-sm text-white/50 xl:flex">
        {attempt.technique_tags.slice(0, 2).map((t) => (
          <span key={t} className="rounded-full bg-white/8 px-2.5 py-0.5">
            {t}
          </span>
        ))}
      </span>
      <span className="flex gap-3 text-2xl" title="naive · guard · full">
        {[d.naive, d.guard, d.full].map((r, i) => (
          <span
            key={i}
            className={`flex h-10 w-10 items-center justify-center rounded-full ring-1 ${r ? OUTCOME_RING[r.outcome] : 'bg-white/5 ring-white/10'} ${
              r?.evaluation === 'shadow' && attempt.pending_rerun ? 'opacity-60' : ''
            } ${r && fresh ? 'animate-pop' : ''}`}
            style={fresh ? { animationDelay: `${i * 140}ms` } : undefined}
          >
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
  const accent = patched ? '34 197 139' : '255 70 90'
  return (
    <div
      className={`absolute inset-0 z-30 flex flex-col items-center justify-center gap-10 overflow-hidden transition-colors duration-1000 ${
        patched ? 'bg-[#03140d]/95' : 'animate-shake bg-[#1a0306]/95'
      }`}
    >
      {/* Pulse rings from the center */}
      <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="animate-burst absolute h-[600px] w-[600px] rounded-full border-2"
            style={{ borderColor: `rgb(${accent} / 0.55)`, animationDelay: `${i * 0.53}s` }}
          />
        ))}
        <span className="absolute h-[900px] w-[900px] rounded-full" style={{ background: `radial-gradient(circle, rgb(${accent} / 0.28), transparent 60%)` }} />
      </div>
      {!patched && <div className="scanlines pointer-events-none absolute inset-0" />}
      {!patched && <div className="pointer-events-none absolute inset-0 animate-pulse shadow-[inset_0_0_180px_40px_rgb(255_40_60/0.55)]" />}

      <div className="relative flex flex-col items-center gap-3">
        <span
          className={`flex h-24 w-24 items-center justify-center rounded-full ${patched ? 'animate-pop bg-[#22c58b]' : 'bg-[#ff3b4a]'}`}
          style={{ boxShadow: `0 0 80px rgb(${accent} / 0.8)` }}
        >
          <Icon name={patched ? 'shieldCheck' : 'alert'} size={48} strokeWidth={2} className="text-white" />
        </span>
        <div
          className={`text-8xl font-black uppercase tracking-tight ${patched ? 'animate-pop text-[#3ee0a1]' : 'animate-glitch text-[#ff4d5a]'}`}
        >
          {patched ? 'Gap closed' : 'Breach found'}
        </div>
        <div className="text-4xl text-white/85">
          by <span className="font-semibold text-white">{nickname}</span>
        </div>
      </div>

      <ol className="relative flex w-[min(900px,90vw)] flex-col gap-3 rounded-[32px] bg-black/40 p-6 text-3xl ring-1 ring-white/10 backdrop-blur">
        {STEPS.map((step, i) => {
          const done = i <= reached
          const current = i === reached + 1 && !patched
          return (
            <li key={step.status} className={`flex items-center gap-4 transition-all duration-500 ${done ? 'text-white' : current ? 'text-white/70' : 'text-white/30'}`}>
              <span
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ring-2 transition-all duration-500 ${
                  done ? 'bg-[#22c58b] ring-[#22c58b]' : current ? 'animate-pulse ring-white/50' : 'ring-white/15'
                }`}
              >
                {done && <Icon name="check" size={22} strokeWidth={3} />}
              </span>
              <span>
                {step.label}
                {step.status === 'proving' && progress?.cases ? ` (${progress.cases} cases)` : ''}
                {step.status === 'enabled' && patched && seconds !== null
                  ? ` in ${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, '0')}`
                  : ''}
              </span>
            </li>
          )
        })}
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10">
          <div
            className="h-full rounded-full bg-gradient-to-r from-[#6d5dfc] to-[#22c58b] transition-all duration-1000"
            style={{ width: `${((reached + 1) / STEPS.length) * 100}%` }}
          />
        </div>
      </ol>
      {progress?.status === 'proved_fail' && (
        <p className="relative text-2xl text-[#f7d23e]">The first rule failed its proof, so it was not enabled.</p>
      )}
      <p className="relative text-xl text-white/55">{BRAND} Autopilot never ships a rule without proof.</p>
    </div>
  )
}
