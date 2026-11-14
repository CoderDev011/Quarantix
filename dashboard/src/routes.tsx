import { lazy, Suspense } from 'react'
import { createBrowserRouter, Navigate } from 'react-router'
import { AppShell } from './components/AppShell.tsx'
import { LoginGate } from './components/LoginGate.tsx'

// "/" is the public product page; the console lives under /app (behind the admin token).
// Arena routes are fixed by docs/features/F16: /arena (phone) and /arena/screen (big screen).

const Landing = lazy(() => import('./pages/Landing.tsx'))
const Live = lazy(() => import('./pages/Live.tsx'))
const Autopilot = lazy(() => import('./pages/Autopilot.tsx'))
const Proof = lazy(() => import('./pages/Proof.tsx'))
const Domains = lazy(() => import('./pages/Domains.tsx'))
const Results = lazy(() => import('./pages/Results.tsx'))
const ArenaAdmin = lazy(() => import('./pages/ArenaAdmin.tsx'))
const ArenaScreen = lazy(() => import('./pages/ArenaScreen.tsx'))
const ArenaPhone = lazy(() => import('./pages/ArenaPhone.tsx'))

export const router = createBrowserRouter([
  {
    path: '/',
    element: (
      <Suspense fallback={<div className="min-h-screen" />}>
        <Landing />
      </Suspense>
    ),
  },
  {
    path: '/app',
    element: (
      <LoginGate>
        <AppShell />
      </LoginGate>
    ),
    children: [
      { index: true, element: <Live /> },
      { path: 'autopilot', element: <Autopilot /> },
      { path: 'proof', element: <Proof /> },
      { path: 'results', element: <Results /> },
      { path: 'domains', element: <Domains /> },
      { path: 'arena', element: <ArenaAdmin /> },
    ],
  },
  // Old console paths keep working (bookmarks, docs).
  { path: '/autopilot', element: <Navigate to="/app/autopilot" replace /> },
  { path: '/proof', element: <Navigate to="/app/proof" replace /> },
  { path: '/results', element: <Navigate to="/app/results" replace /> },
  { path: '/domains', element: <Navigate to="/app/domains" replace /> },
  { path: '/arena-admin', element: <Navigate to="/app/arena" replace /> },
  {
    path: '/arena',
    element: (
      <Suspense fallback={<div className="min-h-screen" />}>
        <ArenaPhone />
      </Suspense>
    ),
  },
  {
    path: '/arena/screen',
    element: (
      <Suspense fallback={<div className="min-h-screen bg-[#07070b]" />}>
        <ArenaScreen />
      </Suspense>
    ),
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
