// The AgentWall mark: a wall of bricks in a rounded tile. Pure SVG, scales anywhere.
import { BRAND } from '../../brand.ts'

export function LogoMark({ size = 32, className = '' }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="aw-g" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#6d5dfc" />
          <stop offset="0.55" stopColor="#a35dfc" />
          <stop offset="1" stopColor="#ff7a1a" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#aw-g)" />
      <g fill="#fff">
        <rect x="6" y="7.5" width="9" height="4.5" rx="1.4" opacity="0.95" />
        <rect x="17" y="7.5" width="9" height="4.5" rx="1.4" opacity="0.7" />
        <rect x="6" y="13.75" width="4" height="4.5" rx="1.4" opacity="0.7" />
        <rect x="12" y="13.75" width="8" height="4.5" rx="1.4" opacity="0.95" />
        <rect x="22" y="13.75" width="4" height="4.5" rx="1.4" opacity="0.7" />
        <rect x="6" y="20" width="9" height="4.5" rx="1.4" opacity="0.85" />
        <rect x="17" y="20" width="9" height="4.5" rx="1.4" opacity="0.95" />
      </g>
    </svg>
  )
}

export function Logo({ size = 30, dark = false }: { size?: number; dark?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <LogoMark size={size} />
      <span className={`text-[17px] font-semibold tracking-tight ${dark ? 'text-white' : 'text-ink'}`}>{BRAND}</span>
    </span>
  )
}
