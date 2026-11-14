// Motion hooks: one-shot in-view detection and eased count-up numbers.
import { useEffect, useRef, useState } from 'react'

const reducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches


/** True once the element has been on screen (for one-shot animations). */
export function useInView<T extends Element>(threshold = 0.3) {
  const ref = useRef<T>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const node = ref.current
    if (!node || seen) return
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true)
        observer.disconnect()
      }
    }, { threshold })
    observer.observe(node)
    return () => observer.disconnect()
  }, [seen, threshold])
  return [ref, seen] as const
}

/** Eases a number from its last shown value to `target`. */
export function useCountUp(target: number, duration = 900): number {
  const [shown, setShown] = useState(target)
  const from = useRef(target)
  useEffect(() => {
    const start = from.current
    if (start === target || reducedMotion()) {
      from.current = target
      setShown(target)
      return
    }
    let frame = 0
    const t0 = performance.now()
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / duration)
      const eased = 1 - Math.pow(1 - p, 3)
      const value = start + (target - start) * eased
      setShown(value)
      from.current = value
      if (p < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [target, duration])
  return shown
}
