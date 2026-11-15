// Motion components with no animation library: scroll reveal, count-up numbers, cursor
// spotlight. All honor prefers-reduced-motion (index.css). Hooks live in hooks/useMotion.ts.
import {
  type CSSProperties,
  type ElementType,
  type MouseEvent,
  type ReactNode,
  useEffect,
  useRef,
} from 'react'
import { useCountUp } from '../../hooks/useMotion.ts'

export function Reveal({
  as: Tag = 'div',
  delay = 0,
  className = '',
  children,
  ...rest
}: {
  as?: ElementType
  delay?: number
  className?: string
  children: ReactNode
  id?: string
}) {
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          node.setAttribute('data-in', '')
          observer.disconnect()
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.12 },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [])
  return (
    <Tag ref={ref} className={`reveal ${className}`} style={{ '--reveal-delay': `${delay}ms` } as CSSProperties} {...rest}>
      {children}
    </Tag>
  )
}

export function CountUp({ value, duration, className }: { value: number; duration?: number; className?: string }) {
  const shown = useCountUp(value, duration)
  return <span className={`tabular ${className ?? ''}`}>{Math.round(shown).toLocaleString()}</span>
}

/** A card whose background follows the cursor with a soft brand glow. */
export function Spotlight({
  as: Tag = 'div',
  className = '',
  children,
  style,
}: {
  as?: ElementType
  className?: string
  children: ReactNode
  style?: CSSProperties
}) {
  const move = (event: MouseEvent<HTMLElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    event.currentTarget.style.setProperty('--mx', `${event.clientX - rect.left}px`)
    event.currentTarget.style.setProperty('--my', `${event.clientY - rect.top}px`)
  }
  return (
    <Tag onMouseMove={move} className={`spotlight ${className}`} style={style}>
      {children}
    </Tag>
  )
}
