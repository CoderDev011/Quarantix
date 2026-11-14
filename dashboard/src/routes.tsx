import { lazy, Suspense } from 'react'
import { createBrowserRouter, NavLink, Outlet } from 'react-router'
import { BRAND } from './brand.ts'
import { LoginGate } from './components/LoginGate.tsx'

// Routes from docs/features/F16 (arena) and plan.md Part 1 section 6 (console).
// Pages not built yet are placeholders; the brief named on the page holds the spec.

const Live = lazy(() => import('./pages/Live.tsx'))

const consolePages = [
  { path: '/policies', label: 'Policies', brief: 'Packs, Autopilot (F18), MCP pins (F14)' },
  { path: '/proof', label: 'Proof wall', brief: 'Real-World Proof Suite (docs/contracts.md section 12)' },
  { path: '/results', label: 'Results', brief: 'Red-team metrics with intervals (contracts section 16)' },
  { path: '/domains', label: 'Domains', brief: 'Domain packs (F03) and the domain generator (F19)' },
]

function ConsoleLayout() {
  return (
    <LoginGate>
      <div className="min-h-screen">
        <header className="flex h-12 items-center gap-6 border-b border-slate-800 px-6">
          <span className="font-semibold tracking-wide">{BRAND}</span>
          <nav className="flex gap-4 text-sm">
            {[{ path: '/', label: 'Live' }, ...consolePages].map((page) => (
              <NavLink
                key={page.path}
                to={page.path}
                end
                className={({ isActive }) => (isActive ? 'text-white' : 'text-slate-400 hover:text-slate-200')}
              >
                {page.label}
              </NavLink>
            ))}
          </nav>
        </header>
        <main className="px-6 pb-4 pt-2">
          <Suspense fallback={<p className="text-slate-500">Loading…</p>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </LoginGate>
  )
}

function Placeholder({ title, brief }: { title: string; brief: string }) {
  return (
    <section>
      <h1 className="text-2xl font-semibold">{title}</h1>
      <p className="mt-2 text-slate-400">Not built yet. Spec: {brief}.</p>
    </section>
  )
}

export const router = createBrowserRouter([
  {
    element: <ConsoleLayout />,
    children: [
      { path: '/', element: <Live /> },
      ...consolePages.map((page) => ({
        path: page.path,
        element: <Placeholder title={page.label} brief={page.brief} />,
      })),
    ],
  },
  { path: '/arena', element: <Placeholder title="Break the Wall" brief="F16 phone page" /> },
  { path: '/arena/screen', element: <Placeholder title="Arena big screen" brief="F16 big screen" /> },
])
