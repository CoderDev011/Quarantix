// Asks for the admin token once and swaps it for an HttpOnly cookie (POST /v1/session).
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Link } from 'react-router'
import { ApiError, api, login } from '../api/client.ts'
import { BRAND } from '../brand.ts'
import { Icon } from './ui/Icon.tsx'
import { Logo, LogoMark } from './ui/Logo.tsx'

export function LoginGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const probe = useQuery({
    queryKey: ['session'],
    queryFn: () => api<unknown>('/v1/agents'),
    retry: false,
  })
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (probe.isPending) {
    return (
      <Centered>
        <span className="relative flex">
          <span className="animate-ring-pulse absolute inset-0 rounded-[14px] bg-brand/40" />
          <LogoMark size={52} className="relative" />
        </span>
        <p className="text-sm text-ink-3">Connecting to the control plane…</p>
      </Centered>
    )
  }
  if (probe.isSuccess) return <>{children}</>
  if (!(probe.error instanceof ApiError && probe.error.status === 401)) {
    return (
      <Centered>
        <LogoMark size={52} />
        <div className="card max-w-md p-6 text-center">
          <p className="font-semibold">Can’t reach the control plane</p>
          <p className="mt-1 text-sm text-ink-3">{String(probe.error)}</p>
          <button type="button" onClick={() => probe.refetch()} className="btn btn-ink mt-5">
            <Icon name="refresh" size={15} /> Try again
          </button>
        </div>
      </Centered>
    )
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(token)
      setToken('')
      await queryClient.invalidateQueries()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="flex flex-col p-6 sm:p-10">
        <Link to="/">
          <Logo />
        </Link>
        <form onSubmit={submit} className="animate-rise m-auto flex w-full max-w-sm flex-col gap-4 py-12">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">Welcome back</h1>
            <p className="mt-2 text-sm text-ink-2">Sign in to the {BRAND} console with your team’s admin token.</p>
          </div>
          <label className="mt-4 text-sm font-medium" htmlFor="token">
            Admin token
          </label>
          <div className="relative">
            <Icon name="key" size={17} className="absolute top-1/2 left-4 -translate-y-1/2 text-ink-3" />
            <input
              id="token"
              type="password"
              autoComplete="current-password"
              autoFocus
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="field pl-11"
              placeholder="••••••••••••••••"
            />
          </div>
          {error && (
            <p className="animate-shake flex items-center gap-2 text-sm text-[#c42b36]">
              <Icon name="alert" size={15} /> {error}
            </p>
          )}
          <button type="submit" disabled={busy || token.length === 0} className="btn btn-ink w-full py-3 text-[15px]">
            {busy ? 'Signing in…' : 'Sign in'} <Icon name="arrowRight" size={16} />
          </button>
          <p className="text-center text-xs text-ink-3">The token becomes an HttpOnly session cookie. It is never stored in the page.</p>
        </form>
      </div>
      <div className="relative m-3 hidden overflow-hidden rounded-5xl bg-ink lg:block">
        <div className="absolute -top-24 -right-24 h-[480px] w-[480px] rounded-full bg-brand/50 blur-[120px] animate-aurora" />
        <div className="absolute -bottom-32 -left-20 h-[420px] w-[420px] rounded-full bg-tangerine/35 blur-[120px] animate-aurora" style={{ animationDelay: '-8s' }} />
        <div className="absolute inset-0 flex items-center justify-center">
          {[180, 260, 340].map((size, i) => (
            <span
              key={size}
              className="absolute rounded-full border border-white/10"
              style={{ width: size * 2, height: size * 2, animation: `spin-slow ${40 + i * 20}s linear infinite` }}
            >
              <span className="absolute top-0 left-1/2 h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-white/70 shadow-[0_0_14px_white]" />
            </span>
          ))}
          <div className="relative flex flex-col items-center gap-5 text-center text-white">
            <LogoMark size={84} className="drop-shadow-[0_20px_40px_rgb(109_93_252/0.6)]" />
            <p className="max-w-xs text-2xl font-semibold leading-snug tracking-tight">
              Every tool call, checked before it runs.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen flex-col items-center justify-center gap-4 px-6">{children}</div>
}
