import { lazy, Suspense } from 'react'
import { createBrowserRouter, NavLink, Outlet } from 'react-router'
import { BRAND } from './brand.ts'
import { LoginGate } from './components/LoginGate.tsx'

// Routes from docs/features/F16 (arena) and plan.md Part 1 section 6 (console).

const Live = lazy(() => import('./pages/Live.tsx'))
const Autopilot = lazy(() => import('./pages/Autopilot.tsx'))
const Proof = lazy(() => import('./pages/Proof.tsx'))
const Domains = lazy(() => import('./pages/Domains.tsx'))
const ArenaAdmin = lazy(() => import('./pages/ArenaAdmin.tsx'))
const ArenaScreen = lazy(() => import('./pages/ArenaScreen.tsx'))

const NAV = [
  { path: '/', label: 'Live' },
  { path: '/autopilot', label: 'Autopilot' },
  { path: '/proof', label: 'Proof wall' },
  { path: '/domains', label: 'Domains' },
  { path: '/arena-admin', label: 'Arena' },
]

function ConsoleLayout() {
  return (
    <LoginGate>
      <div className="min-h-screen">
        <header className="flex h-12 items-center gap-6 border-b border-slate-800 px-6">
          <span className="font-semibold tracking-wide">{BRAND}</span>
          <nav className="flex gap-4 text-sm">
            {NAV.map((page) => (
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
    <section className="p-6">
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
      { path: '/autopilot', element: <Autopilot /> },
      { path: '/proof', element: <Proof /> },
      { path: '/domains', element: <Domains /> },
      { path: '/arena-admin', element: <ArenaAdmin /> },
    ],
  },
  { path: '/arena', element: <Placeholder title="Break the Wall" brief="F16 phone page" /> },
  {
    path: '/arena/screen',
    element: (
      <Suspense fallback={<p className="p-6 text-slate-500">Loading…</p>}>
        <ArenaScreen />
      </Suspense>
    ),
  },
])
