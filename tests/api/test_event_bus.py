"""F13 store, event bus and resumable SSE stream. Spec: docs/features/F13-control-plane.md."""

import asyncio
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from quarantix.api.bus import EventBus
from quarantix.api.sse import event_stream
from quarantix.api.store import Store
from quarantix.core.contracts import Event


def _event(n: int, *, agent: str = "agent-a", run: str = "run-1", kind: str = "tool.call") -> Event:
    return Event(
        event_id=f"e{n}",
        run_id=run,
        agent=agent,
        mode="guard",
        kind=kind,  # type: ignore[arg-type]
        time=datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
        tool="pay",
        data={"n": n},
    )


@pytest.fixture
async def store(tmp_path: Path):  # type: ignore[no-untyped-def]
    store = Store(f"sqlite+aiosqlite:///{tmp_path / 'q.db'}")
    await store.create()
    yield store
    await store.close()


@pytest.fixture
async def bus(store: Store):  # type: ignore[no-untyped-def]
    bus = EventBus(store, flush_interval=0.01)
    await bus.start()
    yield bus
    await bus.stop()


# ---------------------------------------------------------------- store


async def test_inserts_are_idempotent_on_event_id(store: Store) -> None:
    from dataclasses import replace

    batch = [replace(e, seq=i + 1) for i, e in enumerate([_event(1), _event(2)])]
    assert await store.insert_events(batch) == 2
    assert await store.insert_events(batch) == 0  # an SDK retry of the same batch adds nothing
    assert [row["event_id"] for row in await store.events_since(0)] == ["e1", "e2"]


async def test_history_is_ordered_and_filtered(store: Store) -> None:
    from dataclasses import replace

    batch = [
        replace(_event(1, agent="agent-a"), seq=1),
        replace(_event(2, agent="agent-b", run="run-2"), seq=2),
        replace(_event(3, agent="agent-a", kind="limit"), seq=3),
    ]
    await store.insert_events(batch)
    assert [r["seq"] for r in await store.events_since(0)] == [1, 2, 3]
    assert [r["seq"] for r in await store.events_since(1)] == [2, 3]
    assert [r["seq"] for r in await store.events_since(0, agent="agent-a")] == [1, 3]
    assert [r["seq"] for r in await store.events_since(0, run_id="run-2")] == [2]
    assert [r["seq"] for r in await store.events_since(0, kinds=["limit"])] == [3]
    assert [r["seq"] for r in await store.events_since(0, limit=2)] == [1, 2]
    assert await store.max_seq() == 3


async def test_the_database_runs_in_wal_mode(store: Store) -> None:
    assert await store.journal_mode() == "wal"


# ---------------------------------------------------------------- bus


async def test_sequence_numbers_rise_under_concurrency(bus: EventBus) -> None:
    async def emit_many(offset: int) -> None:
        for i in range(50):
            bus.emit(_event(offset + i))
            await asyncio.sleep(0)

    await asyncio.gather(*(emit_many(k * 1000) for k in range(4)))
    await bus.flush()
    seqs = [row["seq"] for row in await bus.store.events_since(0, limit=1000)]
    assert seqs == list(range(1, 201))


async def test_sequence_numbers_continue_after_a_restart(store: Store) -> None:
    first = EventBus(store, flush_interval=0.01)
    await first.start()
    first.emit(_event(1))
    await first.stop()
    second = EventBus(store, flush_interval=0.01)
    await second.start()
    second.emit(_event(2))
    await second.stop()
    assert [r["seq"] for r in await store.events_since(0)] == [1, 2]


async def test_writes_are_batched(store: Store) -> None:
    calls: list[int] = []
    original = store.insert_events

    async def spy(batch):  # type: ignore[no-untyped-def]
        calls.append(len(batch))
        return await original(batch)

    store.insert_events = spy  # type: ignore[method-assign]
    bus = EventBus(store, flush_interval=0.05, batch_size=200)
    await bus.start()
    for i in range(500):
        bus.emit(_event(i))
    await bus.stop()
    assert sum(calls) == 500
    assert len(calls) <= 5


async def test_a_failing_store_never_breaks_emit(store: Store) -> None:
    async def broken(batch):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full")

    store.insert_events = broken  # type: ignore[method-assign]
    bus = EventBus(store, flush_interval=0.01)
    await bus.start()
    bus.emit(_event(1))  # must not raise
    await bus.stop()
    assert bus.write_failures >= 1


# ---------------------------------------------------------------- SSE stream


async def _take(stream, n: int) -> list[dict]:  # type: ignore[no-untyped-def]
    items = []
    async for item in stream:
        items.append(item)
        if len(items) == n:
            break
    return items


async def test_the_stream_sends_backlog_then_live_events_without_gaps_or_duplicates(
    bus: EventBus,
) -> None:
    for i in range(1, 6):
        bus.emit(_event(i))  # some are still unflushed when the client connects
    stream = event_stream(bus, since=0)
    first = await _take(stream, 5)
    for i in range(6, 11):
        bus.emit(_event(i))
    rest = await _take(stream, 5)
    await stream.aclose()
    assert [int(item["id"]) for item in first + rest] == list(range(1, 11))


async def test_a_reconnect_resumes_after_the_last_seen_event(bus: EventBus) -> None:
    for i in range(1, 11):
        bus.emit(_event(i))
    await bus.flush()
    first = event_stream(bus, since=0)
    seen = await _take(first, 4)
    await first.aclose()
    last = int(seen[-1]["id"])
    for i in range(11, 14):
        bus.emit(_event(i))  # emitted while the client was away
    resumed = event_stream(bus, since=last)
    rest = await _take(resumed, 9)
    await resumed.aclose()
    assert [int(item["id"]) for item in seen + rest] == list(range(1, 14))


async def test_stream_filters_apply_to_backlog_and_live(bus: EventBus) -> None:
    bus.emit(_event(1, agent="agent-a"))
    bus.emit(_event(2, agent="agent-b"))
    stream = event_stream(bus, since=0, agent="agent-b")
    (item,) = await _take(stream, 1)
    bus.emit(_event(3, agent="agent-a"))
    bus.emit(_event(4, agent="agent-b"))
    (live,) = await _take(stream, 1)
    await stream.aclose()
    assert (int(item["id"]), int(live["id"])) == (2, 4)


async def test_a_slow_subscriber_is_dropped_with_a_resync_message(store: Store) -> None:
    bus = EventBus(store, flush_interval=0.01, subscriber_queue=3)
    await bus.start()
    stream = event_stream(bus, since=0)
    await _take_nothing_yet(stream, bus)
    for i in range(1, 10):  # the client reads nothing while these arrive
        bus.emit(_event(i))
    items = await _take(stream, 10)
    await bus.stop()
    assert items[-1]["event"] == "resync"


async def _take_nothing_yet(stream, bus: EventBus) -> None:  # type: ignore[no-untyped-def]
    """Start the generator so it subscribes, without consuming any event."""
    bus.emit(_event(0, kind="limit"))
    await _take(stream, 1)


async def test_stream_items_carry_the_event_json(bus: EventBus) -> None:
    bus.emit(_event(1))
    stream = event_stream(bus, since=0)
    (item,) = await _take(stream, 1)
    await stream.aclose()
    import json

    body = json.loads(item["data"])
    assert body["seq"] == 1 and body["event_id"] == "e1" and body["schema_version"] == 1


# ---------------------------------------------------------------- privacy and load


async def test_no_secret_value_ever_reaches_the_database_file(tmp_path: Path) -> None:
    from quarantix.core.labels import Confidentiality
    from quarantix.core.registry import Registry
    from quarantix.engine.approvals import InProcessApprovalBroker
    from quarantix.engine.gate import Gate, GateRuntime
    from quarantix.engine.policy import PolicyBundle
    from tests.engine._factories import arg, request

    database = tmp_path / "secret.db"
    store = Store(f"sqlite+aiosqlite:///{database}")
    await store.create()
    bus = EventBus(store, flush_interval=0.01)
    await bus.start()
    registry = Registry()

    @registry.tool(kind="sink", audience="self", critical_args=("key",))
    def keep(key: str, note: str) -> None:
        """Keep a value."""

    runtime = GateRuntime(Gate(registry, lambda: PolicyBundle(())), InProcessApprovalBroker(), bus)
    secret = "AKIAIOSFODNN7EXAMPLE"
    call = request(
        "keep", key=arg(secret, conf=Confidentiality.SECRET), note=arg(f"copy of {secret}")
    )
    await runtime.enforce(call, lambda: None)
    await bus.stop()
    await store.close()
    raw = b"".join(p.read_bytes() for p in tmp_path.glob("secret.db*"))
    assert secret.encode() not in raw


@pytest.mark.perf
async def test_a_burst_of_5000_events_is_stored_quickly(bus: EventBus) -> None:
    start = time.perf_counter()
    for i in range(5000):
        bus.emit(_event(i))
    emit_time = time.perf_counter() - start
    await bus.flush()
    total = time.perf_counter() - start
    print(f"\nemit 5000 events: {emit_time * 1e3:.1f} ms; stored after {total * 1e3:.0f} ms")
    assert await bus.store.max_seq() == 5000
    assert emit_time < 0.25  # emit stays cheap: < 50 µs per event
