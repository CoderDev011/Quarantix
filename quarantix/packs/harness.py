"""Run a domain's pinned plans against a world through the real Gate (F03 + F05 + F06).

Shared by the red-team runner, the arena and the proof suite, so every way of
running a task judges it the same way.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from quarantix.core.contracts import Event
from quarantix.engine.approvals import ApprovalBroker, AutoApprovalBroker
from quarantix.engine.gate import EventSink, Gate, GateRuntime
from quarantix.engine.interpreter import Limits, Reader, RunContext, RunResult, run_plan
from quarantix.engine.policy import Pack, PolicyBundle, compile_pack
from quarantix.packs.model import Attack, BenignTask, Domain, Plant
from quarantix.packs.world import World


class Recorder:
    """Keeps every event of one run in memory (and forwards to another sink if given)."""

    def __init__(self, forward: EventSink | None = None) -> None:
        self.events: list[Event] = []
        self.forward = forward

    def emit(self, event: Event) -> None:
        self.events.append(event)
        if self.forward is not None:
            self.forward.emit(event)

    def tool_calls(self) -> list[Event]:
        return [e for e in self.events if e.kind == "tool.call"]

    def blocks(self) -> list[Event]:
        return [e for e in self.tool_calls() if e.outcome == "blocked"]

    def asks(self) -> list[Event]:
        return [e for e in self.events if e.kind == "approval.requested"]


@dataclass(slots=True)
class Setup:
    """Everything a run needs, built for one world."""

    world: World
    runtime: GateRuntime
    recorder: Recorder
    approvals: ApprovalBroker
    packs: tuple[Pack, ...] = field(default_factory=tuple)


def policy_packs(
    domain: Domain, *, day_one: bool = False, extra: Iterable[Pack] = ()
) -> tuple[Pack, ...]:
    base = compile_pack(domain.day_one_text) if day_one else domain.policy
    return (base, *extra)


def setup(
    world: World,
    *,
    packs: Iterable[Pack] | None = None,
    policy: Callable[[], PolicyBundle] | None = None,
    approvals: ApprovalBroker | None = None,
    forward: EventSink | None = None,
    offline: Callable[[], bool] = lambda: False,
    tool_timeout: float = 10.0,
) -> Setup:
    """`policy` (a live bundle source, e.g. the control plane's) wins over `packs`."""
    pack_tuple = tuple(packs) if packs is not None else (world.domain.policy,)
    if policy is None:
        bundle = PolicyBundle(pack_tuple)

        def fixed() -> PolicyBundle:
            return bundle

        policy = fixed

    recorder = Recorder(forward)
    broker = approvals if approvals is not None else AutoApprovalBroker("deny")
    runtime = GateRuntime(
        Gate(world.registry, policy, world.lookup),
        broker,
        recorder,
        offline=offline,
        tool_timeout=tool_timeout,
    )
    return Setup(world, runtime, recorder, broker, pack_tuple)


def plant(world: World, item: Attack | BenignTask | Plant | None) -> str | None:
    """Plant an attack's or benign task's payload, using the task's plant target defaults."""
    if item is None:
        return None
    if isinstance(item, Plant):
        target_plant, task_id = item, None
    else:
        target_plant, task_id = item.plant, item.task_id
    if target_plant is None:
        return None
    target = world.domain.tasks[task_id].plant if task_id else None
    use_defaults = target is not None and target.store == target_plant.store
    return world.plant(
        target_plant.store,
        target_plant.record,
        target_plant.field,
        target_plant.payload,
        new_id=target.new_id if use_defaults and target else None,
        defaults=target.defaults if use_defaults and target else None,
    )


async def run_pinned(
    s: Setup,
    task_id: str,
    reader: Reader,
    *,
    run_id: str = "run",
    limits: Limits | None = None,
) -> RunResult:
    domain = s.world.domain
    task = domain.tasks[task_id]
    plan = domain.plans[task.plan]
    ctx = RunContext(run_id=run_id, agent=domain.agent, limits=limits or Limits())
    return await run_plan(
        plan, registry=s.world.registry, runtime=s.runtime, reader=reader, ctx=ctx
    )


def summary(s: Setup) -> dict[str, Any]:
    return {
        "tool_calls": len(s.recorder.tool_calls()),
        "blocks": len(s.recorder.blocks()),
        "asks": len(s.recorder.asks()),
    }
