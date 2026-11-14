"""Resumable event stream (F13): the generator behind the SSE endpoints.

Order matters for "no gap, no duplicate": subscribe first, then send the backlog
(stored events plus the bus's recent ring, for events not flushed yet), then live
events, skipping anything at or below the last sequence sent. Each item's SSE id
is the sequence number, so the browser's automatic reconnect sends
`Last-Event-ID` and resumes exactly where it stopped.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Sequence
from typing import Any

from quarantix.api.bus import RESYNC, EventBus
from quarantix.core.contracts import Event

_PAGE = 500


def _item(wire: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(wire["seq"]),
        "event": "event",
        "data": json.dumps(wire, separators=(",", ":")),
    }


async def event_stream(
    bus: EventBus,
    *,
    since: int = 0,
    agent: str | None = None,
    run_id: str | None = None,
    kinds: Sequence[str] | None = None,
) -> AsyncGenerator[dict[str, str], None]:
    subscription = bus.subscribe(agent=agent, run_id=run_id, kinds=kinds)
    last = since
    try:
        # Backlog: stored pages, then whatever is still only in memory.
        while True:
            page = await bus.store.events_since(
                last, agent=agent, run_id=run_id, kinds=kinds, limit=_PAGE
            )
            for wire in page:
                last = wire["seq"]
                yield _item(wire)
            if len(page) < _PAGE:
                break
        for event in bus.recent_since(last, subscription):
            assert event.seq is not None
            last = event.seq
            yield _item(event.to_wire())
        # Live.
        while True:
            item = await subscription.queue.get()
            if item is RESYNC:
                yield {"event": "resync", "data": json.dumps({"last_seq": last})}
                return
            assert isinstance(item, Event) and item.seq is not None
            if item.seq <= last:
                continue  # already sent from the backlog
            last = item.seq
            yield _item(item.to_wire())
    finally:
        bus.unsubscribe(subscription)
