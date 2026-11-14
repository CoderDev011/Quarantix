// Subscribes to the control plane's SSE feed. The browser reconnects by itself and
// sends Last-Event-ID, so the server resumes without gaps or duplicates. Messages are
// buffered and applied once per animation frame, so bursts never re-render per event.
import { useEffect } from 'react'
import type { EventOut } from '../api/client.ts'
import { useEvents } from '../store/events.ts'

export function useEventStream(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return
    const { addMany, setConnection } = useEvents.getState()
    let buffer: EventOut[] = []
    let frame = 0
    let source: EventSource | null = null
    let closed = false

    const flush = () => {
      frame = 0
      const batch = buffer
      buffer = []
      addMany(batch)
    }

    const open = () => {
      const since = useEvents.getState().lastSeq
      source = new EventSource(`/v1/events/stream?since=${since}`, { withCredentials: true })
      source.onopen = () => setConnection('live')
      source.onerror = () => setConnection('reconnecting') // EventSource retries on its own
      source.addEventListener('event', (message) => {
        buffer.push(JSON.parse((message as MessageEvent<string>).data) as EventOut)
        if (!frame) frame = requestAnimationFrame(flush)
      })
      source.addEventListener('resync', () => {
        // We fell too far behind and were dropped: reopen from the last event we have.
        source?.close()
        if (!closed) open()
      })
    }

    open()
    return () => {
      closed = true
      source?.close()
      if (frame) cancelAnimationFrame(frame)
    }
  }, [enabled])
}
