// The console frame: a floating icon rail on the left (a bottom bar on phones) and a
// pill top bar. Pages render inside <Outlet />.
import { Suspense } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router'
import { BRAND } from '../brand.ts'
import { useEventStream } from '../hooks/useEventStream.ts'
import { useEvents } from '../store/events.ts'
import { Icon, type IconName } from './ui/Icon.tsx'
import { LogoMark } from './ui/Logo.tsx'
import { Skeleton } from './ui/primitives.tsx'

const CONSOLE_NAV: { path: string; label: string; icon: IconName }[] = [
  { path: '/app', label: 'Live', icon: 'activity' },
  { path: '/app/autopilot', label: 'Autopilot', icon: 'sparkles' },
  { path: '/app/proof', label: 'Proof wall', icon: 'shieldCheck' },
  { path: '/app/results', label: 'Results', icon: 'chart' },
  { path: '/app/domains', label: 'Domains', icon: 'layers' },
  { path: '/app/arena', label: 'Arena', icon: 'target' },
]

export function AppShell() {
  useEventStream(true) // one stream for the whole console: the Live page and the top bar both read it
  const location = useLocation()
  const current = CONSOLE_NAV.find((n) => n.path === location.pathname) ?? CONSOLE_NAV[0]
  return (
    <div className="min-h-screen p-3 sm:p-4">
      <aside className="fixed top-4 bottom-4 left-4 z-40 hidden w-[76px] flex-col items-center rounded-[38px] bg-surface py-5 shadow-soft md:flex">
        <Link to="/" className="transition hover:scale-105" aria-label={`${BRAND} home`}>
          <LogoMark size={38} />
        </Link>
        <nav className="mt-9 flex flex-col gap-3">
          {CONSOLE_NAV.map((item) => (
            <RailLink key={item.path} {...item} />
          ))}
        </nav>
        <div className="mt-auto flex flex-col items-center gap-3">
          <a
            href="/arena/screen"
            target="_blank"
            rel="noreferrer"
            className="group relative flex h-12 w-12 items-center justify-center rounded-full bg-surface-2 text-ink-2 transition hover:bg-surface-3 hover:text-ink"
          >
            <Icon name="monitor" size={20} />
            <Tip>Big screen</Tip>
          </a>
          <Link
            to="/"
            className="group relative flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-brand to-tangerine text-sm font-bold text-white"
          >
            AW
            <Tip>Back to site</Tip>
          </Link>
        </div>
      </aside>

      <div className="md:pl-[100px]">
        <TopBar title={current.label} />
        <main className="mx-auto max-w-[1440px] pb-24 md:pb-6">
          <Suspense fallback={<PageSkeleton />}>
            <Outlet />
          </Suspense>
        </main>
      </div>

      <nav className="fixed inset-x-3 bottom-3 z-40 flex justify-around rounded-full bg-ink p-1.5 shadow-lift md:hidden">
        {CONSOLE_NAV.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end
            aria-label={item.label}
            className={({ isActive }) =>
              `flex h-11 w-11 items-center justify-center rounded-full transition ${isActive ? 'bg-white text-ink' : 'text-white/60'}`
            }
          >
            <Icon name={item.icon} size={20} />
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

function RailLink({ path, label, icon }: { path: string; label: string; icon: IconName }) {
  return (
    <NavLink
      to={path}
      end
      aria-label={label}
      className={({ isActive }) =>
        `group relative flex h-12 w-12 items-center justify-center rounded-full transition-all duration-300 ${
          isActive ? 'bg-ink text-white shadow-[0_10px_24px_-10px_rgb(12_13_18/0.8)]' : 'bg-surface-2 text-ink-2 hover:bg-surface-3 hover:text-ink'
        }`
      }
    >
      <Icon name={icon} size={20} />
      <Tip>{label}</Tip>
    </NavLink>
  )
}

function Tip({ children }: { children: string }) {
  return (
    <span className="pointer-events-none absolute left-[60px] whitespace-nowrap rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-white opacity-0 shadow-lift transition duration-200 group-hover:translate-x-1 group-hover:opacity-100">
      {children}
    </span>
  )
}

function TopBar({ title }: { title: string }) {
  const connection = useEvents((s) => s.connection)
  const live = connection === 'live'
  return (
    <div className="mb-6 flex items-center gap-3">
      <div className="flex items-center gap-2 rounded-full bg-surface py-1.5 pr-4 pl-1.5 shadow-soft">
        <span className="flex h-9 items-center rounded-full bg-ink px-4 text-sm font-medium text-white">{BRAND}</span>
        <Icon name="arrowRight" size={14} className="text-ink-3" />
        <span className="text-sm font-medium">{title}</span>
      </div>
      <div className="ml-auto flex items-center gap-2">
        <span
          className={`hidden items-center gap-2 rounded-full px-4 py-2.5 text-xs font-semibold sm:flex ${
            live ? 'bg-mint/15 text-[#0b7a54]' : 'bg-amber/20 text-[#94600a]'
          }`}
          title="Event stream"
        >
          <span className="relative flex h-2 w-2">
            {live && <span className="animate-ring-pulse absolute inset-0 rounded-full bg-mint" />}
            <span className={`relative h-2 w-2 rounded-full ${live ? 'bg-mint' : 'animate-pulse bg-amber'}`} />
          </span>
          {live ? 'Stream live' : connection === 'connecting' ? 'Connecting' : 'Reconnecting'}
        </span>
        <a href="/arena/screen" target="_blank" rel="noreferrer" className="icon-btn" aria-label="Open the big screen">
          <Icon name="monitor" size={18} />
        </a>
        <Link to="/" className="icon-btn" aria-label="Back to the product site">
          <Icon name="home" size={18} />
        </Link>
      </div>
    </div>
  )
}

function PageSkeleton() {
  return (
    <div className="flex flex-col gap-4">
      <Skeleton className="h-10 w-64" />
      <div className="flex gap-3">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-14 w-44 rounded-full" />
        ))}
      </div>
      <Skeleton className="h-[420px] w-full rounded-4xl" />
    </div>
  )
}
