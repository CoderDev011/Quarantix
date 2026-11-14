// The public arena stream (sanitized: no payloads). Reconnects silently with backoff.
import { useEffect, useRef, useState } from 'react'
import type { ArenaStatsOut, AttemptOut, AutopilotProgressOut } from '../api/arena.ts'

export type ArenaFeed = {
  connected: boolean
  stats: ArenaStatsOut | null
  ticker: AttemptOut[]
  autopilot: AutopilotProgressOut | null
  lastResult: AttemptOut | null
}

const TICKER = 12

export function useArenaStream(): ArenaFeed {
  const [feed, setFeed] = useState<ArenaFeed>({
    connected: false,
    stats: null,
    ticker: [],
    autopilot: null,
    lastResult: null,
  })
  const retry = useRef(500)

  useEffect(() => {
    let source: EventSource | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let closed = false

    const connect = () => {
      source = new EventSource('/v1/arena/stream')
      source.onopen = () => {
        retry.current = 500
        setFeed((f) => ({ ...f, connected: true }))
      }
      const read = (raw: MessageEvent<string>) => {
        const message = JSON.parse(raw.data) as {
          type: string
          stats?: ArenaStatsOut
          attempt?: AttemptOut
          autopilot?: AutopilotProgressOut
        }
        setFeed((f) => {
          const next = { ...f, stats: message.stats ?? f.stats }
          if (message.type === 'result' && message.attempt) {
            const attempt = message.attempt
            const rest = f.ticker.filter((a) => a.attempt_id !== attempt.attempt_id)
            next.ticker = [attempt, ...rest].slice(0, TICKER)
            next.lastResult = attempt
          }
          if (message.type === 'autopilot' && message.autopilot) next.autopilot = message.autopilot
          if (message.type === 'reset') next.autopilot = null
          return next
        })
      }
      for (const type of ['stats', 'result', 'autopilot', 'reset', 'goals']) {
        source.addEventListener(type, read as EventListener)
      }
      source.onerror = () => {
        source?.close()
        setFeed((f) => ({ ...f, connected: false }))
        if (!closed) {
          timer = setTimeout(connect, retry.current)
          retry.current = Math.min(retry.current * 2, 10_000)
        }
      }
    }
    connect()
    return () => {
      closed = true
      clearTimeout(timer)
      source?.close()
    }
  }, [])
  return feed
}
