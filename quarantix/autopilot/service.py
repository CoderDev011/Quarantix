"""Policy Autopilot (F18): observe -> draft -> prove -> enforce.

The service never sees payload text: a trigger is an opaque reference that only
the prover resolves. A rule is enabled only after its proof passed; allow-type
rules always need a human; autonomous mode enables tighten-only rules and runs a
canary that rolls back automatically on any failure. Enabling and rolling back
go through the control plane's policy store, so the bundle version (and every
agent) moves within a second.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from quarantix.autopilot.drafter import BreachFacts, Drafter, Observer
from quarantix.autopilot.templates import Candidate, build_pack, pack_name
from quarantix.core.contracts import Event, EventKind
from quarantix.core.registry import Registry
from quarantix.engine.gate import EventSink
from quarantix.engine.policy import Pack, compile_pack

Trigger = Literal["arena_breach", "monitor_findings", "manual", "red_agent_breach"]
Status = Literal[
    "drafted", "proving", "proved_pass", "proved_fail", "enabled", "rejected", "rolled_back"
]


class AutopilotError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Prover(Protocol):
    async def prove(
        self, domain: str, current: tuple[Pack, ...], candidate: Pack, trigger: object | None
    ) -> dict[str, Any]: ...

    async def canary(self, domain: str, packs: tuple[Pack, ...]) -> dict[str, Any]: ...


class PolicyGateway(Protocol):
    """The control plane's policy store, as Autopilot needs it."""

    @property
    def version(self) -> str: ...

    def packs_for(self, agent: str) -> tuple[Pack, ...]: ...

    async def put(self, name: str, text: str) -> str: ...

    async def delete(self, name: str) -> str: ...


@dataclass(slots=True)
class Proposal:
    proposal_id: str
    created: datetime
    trigger: Trigger
    domain: str
    agent: str
    evidence_ids: list[str]
    facts: BreachFacts
    candidates: tuple[Candidate, ...] = ()
    rationale: str = ""
    draft_source: str = ""
    draft_notes: tuple[str, ...] = ()
    pack_name: str = ""
    pack_yaml: str = ""
    proof: dict[str, Any] | None = None
    status: Status = "drafted"
    enabled_by: str | None = None
    breach_time: float = field(default_factory=time.time)
    enabled_time: float | None = None
    enabled_version: str | None = None
    previous_version: str | None = None
    trigger_ref: object | None = field(default=None, repr=False)

    @property
    def tighten_only(self) -> bool:
        return all(c.tighten_only for c in self.candidates)

    def to_wire(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "created": self.created.isoformat(),
            "trigger": self.trigger,
            "domain": self.domain,
            "agent": self.agent,
            "evidence_ids": list(self.evidence_ids),
            "facts": self.facts.to_wire(),
            "candidate_rules": [c.to_wire() for c in self.candidates],
            "tighten_only": self.tighten_only,
            "rationale": self.rationale,
            "draft_source": self.draft_source,
            "draft_notes": list(self.draft_notes),
            "pack_name": self.pack_name,
            "pack_yaml": self.pack_yaml,
            "proof": self.proof,
            "status": self.status,
            "enabled_by": self.enabled_by,
            "seconds_to_patch": (
                round(self.enabled_time - self.breach_time, 1) if self.enabled_time else None
            ),
            "enabled_version": self.enabled_version,
            "previous_version": self.previous_version,
        }


@dataclass(slots=True)
class _Job:
    trigger: Trigger
    facts: BreachFacts
    evidence_ids: list[str]
    trigger_ref: object | None
    breach_time: float
    future: asyncio.Future[Proposal]


class AutopilotService:
    def __init__(
        self,
        *,
        drafter: Drafter,
        prover: Prover,
        policies: PolicyGateway,
        registry_for: Callable[[str], Registry],
        events: EventSink | None = None,
        autonomous: bool = False,
        on_enabled: Callable[[Proposal], None] | None = None,
        canary_interval_s: float = 120.0,
        canary_window_s: float = 600.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.drafter = drafter
        self.prover = prover
        self.policies = policies
        self.registry_for = registry_for
        self.events = events
        self.autonomous = autonomous
        self.on_enabled = on_enabled
        self.canary_interval_s = canary_interval_s
        self.canary_window_s = canary_window_s
        self.clock = clock
        self.observer = Observer()
        self.proposals: dict[str, Proposal] = {}
        self._queue: asyncio.Queue[_Job] = asyncio.Queue(maxsize=50)
        self._worker: asyncio.Task[None] | None = None
        self._canaries: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(self._run())

    async def stop(self) -> None:
        tasks = [t for t in (self._worker, *self._canaries.values()) if t is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._worker = None
        self._canaries.clear()

    # ---------------------------------------------------------------- inputs

    def observe(self, event: Event) -> None:
        self.observer.consume(event)

    async def submit(
        self,
        facts: BreachFacts,
        *,
        trigger: Trigger = "arena_breach",
        evidence_ids: list[str] | None = None,
        trigger_ref: object | None = None,
        breach_time: float | None = None,
    ) -> asyncio.Future[Proposal]:
        """Queue a breach. A second breach of the same shape joins the open proposal."""
        same = self._open_same_shape(facts)
        loop = asyncio.get_running_loop()
        if same is not None:
            same.evidence_ids.extend(evidence_ids or [])
            done: asyncio.Future[Proposal] = loop.create_future()
            done.set_result(same)
            return done
        future: asyncio.Future[Proposal] = loop.create_future()
        job = _Job(trigger, facts, list(evidence_ids or []), trigger_ref,
                   breach_time or self.clock(), future)  # fmt: skip
        try:
            self._queue.put_nowait(job)
        except asyncio.QueueFull:
            raise AutopilotError(
                429, "autopilot_busy", "Autopilot has too many open breaches"
            ) from None
        return future

    def _open_same_shape(self, facts: BreachFacts) -> Proposal | None:
        for proposal in self.proposals.values():
            if proposal.status in ("drafted", "proving", "proved_pass") and (
                proposal.domain,
                proposal.facts.goal_kind,
                proposal.facts.tool,
            ) == (facts.domain, facts.goal_kind, facts.tool):
                return proposal
        return None

    # ---------------------------------------------------------------- the pipeline

    async def _run(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                proposal = await self.propose(
                    job.facts, trigger=job.trigger, evidence_ids=job.evidence_ids,
                    trigger_ref=job.trigger_ref, breach_time=job.breach_time,
                )  # fmt: skip
                if not job.future.done():
                    job.future.set_result(proposal)
            except Exception as exc:  # one bad breach never stops Autopilot
                if not job.future.done():
                    job.future.set_exception(exc)
            finally:
                self._queue.task_done()

    async def propose(
        self,
        facts: BreachFacts,
        *,
        trigger: Trigger = "manual",
        evidence_ids: list[str] | None = None,
        trigger_ref: object | None = None,
        breach_time: float | None = None,
    ) -> Proposal:
        registry = self.registry_for(facts.domain)
        proposal = Proposal(
            proposal_id=uuid.uuid4().hex[:10],
            created=datetime.now(UTC),
            trigger=trigger,
            domain=facts.domain,
            agent=facts.agent,
            evidence_ids=list(evidence_ids or []),
            facts=facts,
            breach_time=breach_time or self.clock(),
            trigger_ref=trigger_ref,
        )
        draft = await self.drafter.draft(facts, self.observer.stats_for(facts.agent), registry)
        proposal.candidates = draft.candidates
        proposal.rationale = draft.rationale
        proposal.draft_source = draft.source
        proposal.draft_notes = draft.notes
        proposal.pack_name = pack_name(proposal.proposal_id)
        proposal.pack_yaml = build_pack(proposal.proposal_id, facts.agent, draft.candidates)
        self.proposals[proposal.proposal_id] = proposal
        self._emit("autopilot.proposal", proposal)

        proposal.status = "proving"
        current = self.policies.packs_for(facts.agent)
        candidate = compile_pack(proposal.pack_yaml)
        try:
            proof = await self.prover.prove(facts.domain, current, candidate, trigger_ref)
        except Exception as exc:
            proof = {
                "verdict": "fail",
                "reasons": [f"the proof could not run: {type(exc).__name__}"],
            }
        proposal.proof = proof
        proposal.status = "proved_pass" if proof.get("verdict") == "pass" else "proved_fail"
        self._emit("autopilot.proof", proposal)
        if self.autonomous and proposal.status == "proved_pass" and proposal.tighten_only:
            await self.enable(proposal.proposal_id, by="autonomous")
        return proposal

    # ---------------------------------------------------------------- actions

    def get(self, proposal_id: str) -> Proposal:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise AutopilotError(404, "not_found", "no such proposal")
        return proposal

    def list(self) -> list[Proposal]:
        return sorted(self.proposals.values(), key=lambda p: p.created, reverse=True)

    async def enable(self, proposal_id: str, *, by: str = "human") -> Proposal:
        async with self._lock:
            proposal = self.get(proposal_id)
            if proposal.status != "proved_pass":
                raise AutopilotError(
                    409, "not_proved", "only a proposal whose proof passed can be enabled"
                )
            if by == "autonomous" and not proposal.tighten_only:
                raise AutopilotError(403, "needs_human", "allow-type rules always need a human")
            proposal.previous_version = self.policies.version
            proposal.enabled_version = await self.policies.put(
                proposal.pack_name, proposal.pack_yaml
            )
            proposal.status = "enabled"
            proposal.enabled_by = (
                by if by == "autonomous" or by.startswith("human") else f"human:{by}"
            )
            proposal.enabled_time = self.clock()
        self._emit("autopilot.enabled", proposal)
        if self.on_enabled is not None:
            with contextlib.suppress(Exception):
                self.on_enabled(proposal)
        if by == "autonomous":
            self._canaries[proposal_id] = asyncio.create_task(self._canary(proposal))
        return proposal

    async def reject(self, proposal_id: str) -> Proposal:
        proposal = self.get(proposal_id)
        if proposal.status == "enabled":
            raise AutopilotError(409, "enabled", "roll back an enabled proposal instead")
        proposal.status = "rejected"
        self._emit("autopilot.proposal", proposal)
        return proposal

    async def rollback(self, proposal_id: str, *, reason: str = "manual") -> Proposal:
        async with self._lock:
            proposal = self.get(proposal_id)
            if proposal.status != "enabled":
                raise AutopilotError(
                    409, "not_enabled", "only an enabled proposal can be rolled back"
                )
            if self.policies.version != proposal.enabled_version:
                raise AutopilotError(
                    409, "newer_changes",
                    "the policy changed after this rule was enabled: merge by hand",
                )  # fmt: skip
            version = await self.policies.delete(proposal.pack_name)
            proposal.status = "rolled_back"
        task = self._canaries.pop(proposal_id, None)
        if task is not None and task is not asyncio.current_task():
            task.cancel()
        self._emit("autopilot.rolled_back", proposal, {"reason": reason, "bundle_version": version})
        return proposal

    async def _canary(self, proposal: Proposal) -> None:
        """Benign replays every interval during the window; any failure rolls back."""
        deadline = self.clock() + self.canary_window_s
        while self.clock() < deadline and proposal.status == "enabled":
            await asyncio.sleep(self.canary_interval_s)
            packs = self.policies.packs_for(proposal.agent)
            try:
                result = await self.prover.canary(proposal.domain, packs)
            except Exception as exc:
                result = {"passed": False, "reasons": [type(exc).__name__]}
            self._emit("canary.result", proposal, result)
            if not result.get("passed"):
                with contextlib.suppress(AutopilotError):
                    await self.rollback(proposal.proposal_id, reason="canary failed")
                return

    # ---------------------------------------------------------------- events

    def _emit(
        self, kind: EventKind, proposal: Proposal, extra: Mapping[str, Any] | None = None
    ) -> None:
        if self.events is None:
            return
        data = {
            "proposal_id": proposal.proposal_id,
            "status": proposal.status,
            "domain": proposal.domain,
            "candidate_rules": [c.to_wire() for c in proposal.candidates],
            "verdict": (proposal.proof or {}).get("verdict"),
            "seconds_to_patch": proposal.to_wire()["seconds_to_patch"],
            **dict(extra or {}),
        }
        with contextlib.suppress(Exception):
            self.events.emit(
                Event(
                    event_id=uuid.uuid4().hex, run_id=f"autopilot-{proposal.proposal_id}",
                    agent=proposal.agent, mode="guard", kind=kind, time=datetime.now(UTC),
                    data=data,
                )
            )  # fmt: skip
