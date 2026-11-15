// Shared console building blocks: page header, stat chip, icon dot, pills, toggles.
import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon.tsx'
import { CountUp } from './motion.tsx'

export type Tone = 'ink' | 'brand' | 'tangerine' | 'sun' | 'lilac' | 'sky' | 'mint' | 'rose' | 'amber' | 'neutral'

const DOT: Record<Tone, string> = {
  ink: 'bg-ink text-white',
  brand: 'bg-brand text-white',
  tangerine: 'bg-tangerine text-white',
  sun: 'bg-sun text-ink',
  lilac: 'bg-lilac text-ink',
  sky: 'bg-sky text-white',
  mint: 'bg-mint text-white',
  rose: 'bg-rose text-white',
  amber: 'bg-amber text-ink',
  neutral: 'bg-surface-2 text-ink-2',
}

/** A colored circle holding an icon, like the device dots in the inspiration. */
export function IconDot({ icon, tone = 'neutral', size = 36 }: { icon: IconName; tone?: Tone; size?: number }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center justify-center rounded-full ${DOT[tone]}`}
      style={{ width: size, height: size }}
    >
      <Icon name={icon} size={Math.round(size * 0.5)} />
    </span>
  )
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
}: {
  eyebrow?: string
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
}) {
  return (
    <header className="animate-rise flex flex-wrap items-end gap-4">
      <div className="min-w-0">
        {eyebrow && <p className="eyebrow mb-1.5">{eyebrow}</p>}
        <h1 className="text-[2rem] font-semibold leading-tight tracking-tight">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="ml-auto flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}

/** A pill-shaped live metric: icon dot, animated number, label. */
export function StatChip({
  icon,
  tone,
  value,
  label,
  badge,
}: {
  icon: IconName
  tone: Tone
  value: number | string
  label: string
  badge?: ReactNode
}) {
  return (
    <div className="relative flex min-w-[10.5rem] items-center gap-3 rounded-full bg-surface py-2 pl-2 pr-6 shadow-soft">
      <IconDot icon={icon} tone={tone} size={40} />
      <div className="leading-tight">
        <div className="text-[17px] font-semibold">
          {typeof value === 'number' ? <CountUp value={value} /> : value}
        </div>
        <div className="text-xs text-ink-3">{label}</div>
      </div>
      {badge && <span className="absolute -top-2 right-3">{badge}</span>}
    </div>
  )
}

const PILL: Record<string, string> = {
  good: 'bg-mint/15 text-[#0b7a54]',
  bad: 'bg-rose/12 text-[#c42b36]',
  warn: 'bg-amber/18 text-[#94600a]',
  info: 'bg-sky/15 text-[#1d6fb8]',
  brand: 'bg-brand-soft text-brand',
  neutral: 'bg-surface-2 text-ink-2',
  ink: 'bg-ink text-white',
}

export type PillTone = keyof typeof PILL

export function Pill({
  tone = 'neutral',
  icon,
  children,
  className = '',
}: {
  tone?: PillTone
  icon?: IconName
  children: ReactNode
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-semibold ${PILL[tone]} ${className}`}
    >
      {icon && <Icon name={icon} size={13} strokeWidth={2.2} />}
      {children}
    </span>
  )
}

/** The black-and-white switch from the inspiration. */
export function Toggle({
  on,
  onChange,
  label,
  disabled,
}: {
  on: boolean
  onChange: (on: boolean) => void
  label: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={`relative h-7 w-12 shrink-0 rounded-full transition-colors duration-300 disabled:opacity-40 ${
        on ? 'bg-ink' : 'bg-surface-3'
      }`}
    >
      <span
        className={`absolute top-0.5 h-6 w-6 rounded-full bg-white shadow-[0_2px_6px_rgb(0_0_0/0.25)] transition-all duration-300 ${
          on ? 'left-[22px]' : 'left-0.5'
        }`}
      />
    </button>
  )
}

/** Segmented control: the active option is an ink pill. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  tone,
}: {
  options: readonly T[]
  value: T
  onChange: (value: T) => void
  tone?: (value: T) => string
}) {
  return (
    <div className="inline-flex rounded-full bg-surface-2 p-1">
      {options.map((option) => {
        const active = option === value
        return (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={`rounded-full px-3 py-1 text-xs font-semibold capitalize transition-all duration-300 ${
              active ? (tone?.(option) ?? 'bg-ink text-white shadow-soft') : 'text-ink-3 hover:text-ink'
            }`}
          >
            {option}
          </button>
        )
      })}
    </div>
  )
}

export function EmptyState({ icon, title, children }: { icon: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <span className="relative inline-flex">
        <span className="animate-ring-pulse absolute inset-0 rounded-full bg-brand/25" />
        <IconDot icon={icon} tone="brand" size={52} />
      </span>
      <p className="font-semibold">{title}</p>
      {children && <div className="max-w-sm text-sm text-ink-3">{children}</div>}
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton rounded-2xl ${className}`} />
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 rounded-2xl bg-rose/10 px-4 py-3 text-sm text-[#c42b36]">
      <Icon name="alert" size={16} /> {children}
    </p>
  )
}
