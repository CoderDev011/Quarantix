// The live event store: a ring of the latest events, de-duplicated by sequence number.
import { create } from 'zustand'
import type { EventOut } from '../api/client.ts'

export const RING_SIZE = 2000

export type Connection = 'connecting' | 'live' | 'reconnecting'

type EventState = {
  events: EventOut[] // ascending by seq, at most RING_SIZE
  lastSeq: number
  connection: Connection
  selectedSeq: number | null // null = follow the newest blocked call
  addMany: (incoming: EventOut[]) => void
  setConnection: (connection: Connection) => void
  select: (seq: number | null) => void
}

export const useEvents = create<EventState>((set) => ({
  events: [],
  lastSeq: 0,
  connection: 'connecting',
  selectedSeq: null,
  addMany: (incoming) =>
    set((state) => {
      const fresh = incoming.filter((e) => (e.seq ?? 0) > state.lastSeq)
      if (fresh.length === 0) return state
      const events = [...state.events, ...fresh].slice(-RING_SIZE)
      return { events, lastSeq: events[events.length - 1].seq ?? state.lastSeq }
    }),
  setConnection: (connection) => set({ connection }),
  select: (selectedSeq) => set({ selectedSeq }),
}))

/** A call the Gate stopped (or, in monitor mode, would have stopped). */
export const isStopped = (e: EventOut) =>
  e.kind === 'tool.call' && (e.decision?.kind === 'block' || e.outcome === 'blocked')
