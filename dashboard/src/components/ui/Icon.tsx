// A small inline icon set (24×24, 1.75 stroke). No icon library: AGENTS.md §6.
import type { ReactNode, SVGProps } from 'react'

const ICONS = {
  activity: <path d="M22 12h-4l-3 8L9 4l-3 8H2" />,
  sparkles: (
    <>
      <path d="M11 3l1.9 4.9L18 10l-5.1 2.1L11 17l-1.9-4.9L4 10l5.1-2.1z" />
      <path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z" />
    </>
  ),
  shield: <path d="M12 3l8 3v6c0 4.6-3.4 8.3-8 9-4.6-.7-8-4.4-8-9V6z" />,
  shieldCheck: (
    <>
      <path d="M12 3l8 3v6c0 4.6-3.4 8.3-8 9-4.6-.7-8-4.4-8-9V6z" />
      <path d="M8.5 12.2l2.4 2.4 4.6-4.8" />
    </>
  ),
  shieldX: (
    <>
      <path d="M12 3l8 3v6c0 4.6-3.4 8.3-8 9-4.6-.7-8-4.4-8-9V6z" />
      <path d="M9.5 9.5l5 5m0-5l-5 5" />
    </>
  ),
  chart: (
    <>
      <path d="M3 21h18" />
      <path d="M6 17v-5M11 17V6M16 17v-8M20.5 17v-3" />
    </>
  ),
  layers: (
    <>
      <path d="M12 3l9 4.8-9 4.8-9-4.8z" />
      <path d="M3 12.2l9 4.8 9-4.8M3 16.6l9 4.8 9-4.8" />
    </>
  ),
  target: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.4" fill="currentColor" />
    </>
  ),
  home: (
    <>
      <path d="M4 10.5L12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" />
    </>
  ),
  monitor: (
    <>
      <rect x="3" y="4" width="18" height="12.5" rx="2.5" />
      <path d="M8.5 20.5h7M12 16.5v4" />
    </>
  ),
  arrowRight: <path d="M5 12h14m-5-5l5 5-5 5" />,
  arrowUpRight: <path d="M7 17L17 7M8.5 7H17v8.5" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  plus: <path d="M12 5v14M5 12h14" />,
  play: <path d="M7 4.5v15l12.5-7.5z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  refresh: (
    <>
      <path d="M20 11a8 8 0 0 0-14.6-4.5L4 8" />
      <path d="M4 3.5V8h4.5M4 13a8 8 0 0 0 14.6 4.5L20 16" />
      <path d="M20 20.5V16h-4.5" />
    </>
  ),
  mail: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <path d="M3.5 6.5l8.5 6.5 8.5-6.5" />
    </>
  ),
  card: (
    <>
      <rect x="2.5" y="5" width="19" height="14" rx="2.5" />
      <path d="M2.5 9.5h19M6.5 15h4" />
    </>
  ),
  chat: <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H10l-5 4v-4.2A2.5 2.5 0 0 1 4 13.5z" />,
  terminal: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2.5" />
      <path d="M7 9.5l3 2.5-3 2.5M12.5 15H17" />
    </>
  ),
  database: (
    <>
      <ellipse cx="12" cy="5.5" rx="8" ry="2.8" />
      <path d="M4 5.5v13c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8v-13M4 12c0 1.5 3.6 2.8 8 2.8s8-1.3 8-2.8" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.6 3.7 5.6 3.7 9s-1.2 6.4-3.7 9c-2.5-2.6-3.7-5.6-3.7-9S9.5 5.6 12 3z" />
    </>
  ),
  git: (
    <>
      <circle cx="6" cy="6" r="2.2" />
      <circle cx="6" cy="18" r="2.2" />
      <circle cx="18" cy="8" r="2.2" />
      <path d="M6 8.2v7.6M18 10.2c0 4-6 3.4-10.4 6.4" />
    </>
  ),
  key: (
    <>
      <circle cx="8" cy="15" r="4.5" />
      <path d="M11.2 11.8L20 3m-4 4l2.5 2.5M14 9l2 2" />
    </>
  ),
  ticket: (
    <>
      <path d="M3 8a2 2 0 0 0 0 4 2 2 0 0 1 0 4v2.5h18V16a2 2 0 0 1 0-4 2 2 0 0 0 0-4V5.5H3z" />
      <path d="M14 6v3m0 3v1.5m0 3V18" />
    </>
  ),
  cloud: <path d="M7 18.5a4.5 4.5 0 0 1-.6-9 6 6 0 0 1 11.6 1.5A3.8 3.8 0 0 1 17.5 18.5z" />,
  bolt: <path d="M13 2.5L4.5 13.5H11l-1 8 8.5-11H12z" />,
  eye: (
    <>
      <path d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  lock: (
    <>
      <rect x="4.5" y="10.5" width="15" height="10.5" rx="2.5" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.5L22 20H2z" />
      <path d="M12 10v4.5M12 17.2v.3" />
    </>
  ),
  hand: (
    <path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11m0-6.5a1.5 1.5 0 0 1 3 0V11m0-5a1.5 1.5 0 0 1 3 0v6m0-3.5a1.5 1.5 0 0 1 3 0V15a7 7 0 0 1-7 7h-1a7 7 0 0 1-5.6-2.8L3.6 15.4a1.6 1.6 0 0 1 2.5-2z" />
  ),
  robot: (
    <>
      <rect x="4" y="7.5" width="16" height="12" rx="3" />
      <path d="M12 3.5v4M9 13v1M15 13v1M2 12.5v3M22 12.5v3" />
    </>
  ),
  plug: (
    <>
      <path d="M9 3v4.5M15 3v4.5" />
      <path d="M6 7.5h12V11a6 6 0 0 1-12 0z" />
      <path d="M12 17v4" />
    </>
  ),
  cpu: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M10 10h4v4h-4zM9 2.5V6m6-3.5V6M9 18v3.5m6-3.5v3.5M2.5 9H6m-3.5 6H6M18 9h3.5M18 15h3.5" />
    </>
  ),
  trophy: (
    <>
      <path d="M7 4h10v5a5 5 0 0 1-10 0z" />
      <path d="M7 6H3.5v1.5A3.5 3.5 0 0 0 7 11M17 6h3.5v1.5A3.5 3.5 0 0 1 17 11M12 14v3.5M8 21h8l-1-3.5H9z" />
    </>
  ),
  flame: (
    <path d="M12 21.5c-4 0-7-2.8-7-6.6 0-3 1.8-4.8 3.3-6.4.4 1.7 1.3 2.7 2.4 3.1C10.3 7.6 12 4.6 14.6 2.5c.2 3 1.9 4.6 3.1 6.3 1 1.4 1.3 2.8 1.3 4.6 0 4.6-3 8.1-7 8.1z" />
  ),
  logout: <path d="M14 4h4.5A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5H14M10 16.5L5.5 12 10 7.5M5.5 12H15" />,
  code: <path d="M8.5 7L3.5 12l5 5M15.5 7l5 5-5 5M13.5 4.5l-3 15" />,
  file: (
    <>
      <path d="M6 2.5h8l5 5v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-17a1 1 0 0 1 1-1z" />
      <path d="M13.5 2.5v5.5H19M8.5 13h7M8.5 17h5" />
    </>
  ),
  link: (
    <>
      <path d="M10 14a4.5 4.5 0 0 0 6.4 0l3-3a4.5 4.5 0 0 0-6.4-6.4l-1.2 1.2" />
      <path d="M14 10a4.5 4.5 0 0 0-6.4 0l-3 3a4.5 4.5 0 0 0 6.4 6.4l1.2-1.2" />
    </>
  ),
  qr: (
    <>
      <rect x="3.5" y="3.5" width="6.5" height="6.5" rx="1.2" />
      <rect x="14" y="3.5" width="6.5" height="6.5" rx="1.2" />
      <rect x="3.5" y="14" width="6.5" height="6.5" rx="1.2" />
      <path d="M14 14h2.5v2.5H14zM18 18h2.5v2.5H18zM14 19h1.5M19 14h1.5" />
    </>
  ),
  user: (
    <>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </>
  ),
  dot: <circle cx="12" cy="12" r="4" fill="currentColor" stroke="none" />,
  gauge: (
    <>
      <path d="M3.5 17a9 9 0 1 1 17 0" />
      <path d="M12 13.5l4-5" />
      <circle cx="12" cy="14" r="1.6" fill="currentColor" />
    </>
  ),
  eyeOff: (
    <>
      <path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3 3.9M6.6 6.6C3.9 8.4 2.5 12 2.5 12S6 19 12 19a9.6 9.6 0 0 0 5.3-1.6" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </>
  ),
} satisfies Record<string, ReactNode>

export type IconName = keyof typeof ICONS

export function Icon({
  name,
  size = 18,
  strokeWidth = 1.75,
  ...rest
}: { name: IconName; size?: number; strokeWidth?: number } & Omit<SVGProps<SVGSVGElement>, 'name'>) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      {ICONS[name]}
    </svg>
  )
}
