// Asks for the admin token once and swaps it for an HttpOnly cookie (POST /v1/session).
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, type ReactNode, useState } from 'react'
import { ApiError, api, login } from '../api/client.ts'
import { BRAND } from '../brand.ts'

export function LoginGate({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const probe = useQuery({
    queryKey: ['session'],
    queryFn: () => api<unknown>('/v1/agents'),
    retry: false,
  })
  const [token, setToken] = useState('')
  const [error, setError] = useState<string | null>(null)

  if (probe.isPending) return <p className="p-6 text-slate-400">Connecting…</p>
  if (probe.isSuccess) return <>{children}</>
  if (!(probe.error instanceof ApiError && probe.error.status === 401)) {
    return <p className="p-6 text-red-400">Cannot reach the control plane: {String(probe.error)}</p>
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    try {
      await login(token)
      setToken('')
      await queryClient.invalidateQueries()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Login failed')
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto mt-24 flex max-w-sm flex-col gap-3 rounded border border-slate-800 p-6">
      <h1 className="text-lg font-semibold">{BRAND} console</h1>
      <label className="text-sm text-slate-400" htmlFor="token">
        Admin token
      </label>
      <input
        id="token"
        type="password"
        autoComplete="current-password"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        className="rounded border border-slate-700 bg-slate-900 px-3 py-2"
      />
      {error && <p className="text-sm text-red-400">{error}</p>}
      <button type="submit" className="rounded bg-emerald-600 px-3 py-2 font-medium hover:bg-emerald-500">
        Sign in
      </button>
    </form>
  )
}
