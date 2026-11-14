import { createBrowserRouter, NavLink, Outlet } from 'react-router'

// Routes from docs/features/F16 (arena) and plan.md Part 1 section 6 (console).
// Each page is a placeholder until its feature lands; the brief named on the page holds the spec.

const consolePages = [
  { path: '/', label: 'Live', brief: 'Live feed, agent cards, approvals inbox, provenance graph' },
  { path: '/policies', label: 'Policies', brief: 'Packs, Autopilot (F18), MCP pins (F14)' },
  { path: '/proof', label: 'Proof wall', brief: 'Real-World Proof Suite (docs/contracts.md section 12)' },
  { path: '/results', label: 'Results', brief: 'Red-team metrics with intervals (contracts section 16)' },
  { path: '/domains', label: 'Domains', brief: 'Domain packs (F03) and the domain generator (F19)' },
]

function ConsoleLayout() {
  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-6 border-b border-slate-800 px-6 py-3">
        <span className="font-semibold tracking-wide">Quarantix</span>
        <nav className="flex gap-4 text-sm">
          {consolePages.map((page) => (
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
      <main className="p-6">
        <Outlet />
      </main>
    </div>
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
    children: consolePages.map((page) => ({
      path: page.path,
      element: <Placeholder title={page.label} brief={page.brief} />,
    })),
  },
  { path: '/arena', element: <Placeholder title="Break the Wall" brief="F16 phone page" /> },
  { path: '/arena/screen', element: <Placeholder title="Arena big screen" brief="F16 big screen" /> },
])
