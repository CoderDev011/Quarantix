"""Event bus (F13): sequence numbers, live broadcast, batched writes.

`emit` is synchronous and cheap: it stamps the next sequence number, keeps the
event in a ring of recent events (so a client connecting before the next flush
still gets it), queues it for writing and pushes it to every matching
subscriber. A writer task stores events every `flush_interval` seconds or every
`batch_size` events, in one transaction. A subscriber whose queue fills up is
dropped and sent a resync marker, so one slow browser can never grow memory.
Single process by design (docs/DECISIONS.md); sequence numbers continue from the
highest stored value after a restart.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Final

from quarantix.api.store import Store
from quarantix.core.contracts import Event

RESYNC: Final = object()  # put on a dropped subscriber's queue


@dataclass(eq=False, slots=True)
class Subscription:
    queue: asyncio.Queue[object]
    agent: str | None = None
    run_id: str | None = None
    kinds: frozenset[str] | None = None
    dropped: bool = field(default=False)

    def matches(self, item: Event) -> bool:
        return (
            (self.agent is None or item.agent == self.agent)
            and (self.run_id is None or item.run_id == self.run_id)
            and (self.kinds is None or item.kind in self.kinds)
        )


class EventBus:
    def __init__(
        self,
        store: Store,
        *,
        flush_interval: float = 0.1,
        batch_size: int = 200,
        subscriber_queue: int = 1000,
        recent: int = 2000,
        max_pending: int = 50_000,
    ) -> None:
        self.store = store
        self.flush_interval = flush_interval
        self.batch_size = batch_size
        self.subscriber_queue = subscriber_queue
        self.max_pending = max_pending
        self._recent: deque[Event] = deque(maxlen=recent)
        self._pending: deque[Event] = deque()
        self._subscribers: set[Subscription] = set()
        self._seq = 0
        self._wake = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._writer: asyncio.Task[None] | None = None
        self._running = False
        self.write_failures = 0
        self.dropped_events = 0

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        self._seq = await self.store.max_seq()
        self._running = True
        self._writer = asyncio.create_task(self._write_loop(), name="event-bus-writer")

    async def stop(self) -> None:
        self._running = False
        self._wake.set()
        if self._writer is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._writer
        await self.flush()

    # ---------------------------------------------------------------- emit and subscribe

    def emit(self, event: Event) -> None:
        self._seq += 1
        stamped = replace(event, seq=self._seq)
        self._recent.append(stamped)
        self._pending.append(stamped)
        if len(self._pending) > self.max_pending:  # the store is far behind: keep memory bounded
            self._pending.popleft()
            self.dropped_events += 1
        if len(self._pending) >= self.batch_size:
            self._wake.set()
        for subscriber in list(self._subscribers):
            if not subscriber.matches(stamped):
                continue
            try:
                subscriber.queue.put_nowait(stamped)
            except asyncio.QueueFull:
                self._drop(subscriber)

    def subscribe(
        self,
        *,
        agent: str | None = None,
        run_id: str | None = None,
        kinds: Sequence[str] | None = None,
    ) -> Subscription:
        subscription = Subscription(
            asyncio.Queue(maxsize=self.subscriber_queue + 1),  # +1 leaves room for RESYNC
            agent,
            run_id,
            frozenset(kinds) if kinds else None,
        )
        self._subscribers.add(subscription)
        return subscription

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subscribers.discard(subscription)

    def recent_since(self, since: int, subscription: Subscription) -> list[Event]:
        return [
            item
            for item in self._recent
            if item.seq is not None and item.seq > since and subscription.matches(item)
        ]

    def _drop(self, subscription: Subscription) -> None:
        subscription.dropped = True
        self._subscribers.discard(subscription)
        while not subscription.queue.empty():
            subscription.queue.get_nowait()
        subscription.queue.put_nowait(RESYNC)

    # ---------------------------------------------------------------- writing

    async def flush(self) -> None:
        async with self._write_lock:
            while self._pending:
                batch = [
                    self._pending.popleft() for _ in range(min(self.batch_size, len(self._pending)))
                ]
                try:
                    await self.store.insert_events(batch)
                except Exception:  # never crash the bus; the events stay in the recent ring
                    self.write_failures += 1

    async def _write_loop(self) -> None:
        while self._running:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self.flush_interval)
            self._wake.clear()
            await self.flush()
