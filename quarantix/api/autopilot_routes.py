"""Autopilot HTTP routes (F18) and the glue between the arena, Autopilot and the policy store.

No `from __future__ import annotations`: FastAPI resolves these type hints at import.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from quarantix.api.policies import PolicyService
from quarantix.api.store import Store
from quarantix.arena.prover import ArenaTrigger, ReplayProver, breach_facts
from quarantix.arena.service import ArenaService, Attempt
from quarantix.arena.suite import Trace, load_traces
from quarantix.autopilot.drafter import BreachFacts, Drafter
from quarantix.autopilot.service import AutopilotError, AutopilotService, Proposal
from quarantix.core.contracts import Event
from quarantix.engine.policy import Pack
from quarantix.packs.model import Domain


class PolicyGateway:
    """Autopilot's view of the control plane's policy store."""

    def __init__(self, policies: PolicyService) -> None:
        self.policies = policies

    @property
    def version(self) -> str:
        return self.policies.version

    def packs_for(self, agent: str) -> tuple[Pack, ...]:
        return tuple(
            p for p in self.policies.bundle.packs if "*" in p.applies_to or agent in p.applies_to
        )

    async def put(self, name: str, text: str) -> str:
        return await self.policies.put_pack(name, text)

    async def delete(self, name: str) -> str:
        return await self.policies.delete_pack(name)


def load_all_traces(root: Path, domains: dict[str, Domain]) -> dict[str, dict[str, Trace]]:
    return {name: load_traces(root / f"{name}.json") for name in domains}


def build_autopilot(
    *,
    domains: dict[str, Domain],
    policies: PolicyService,
    store: Store,
    events: Any,
    drafter: Drafter,
    traces_dir: Path,
    arena: ArenaService | None,
) -> AutopilotService:
    traces = load_all_traces(traces_dir, domains)

    async def decisions(agent: str) -> list[Event]:
        newest = await store.max_seq()
        rows = await store.events_since(
            max(0, newest - 20_000), agent=agent, kinds=["tool.call"], limit=500
        )
        found = []
        for row in rows:
            with contextlib.suppress(ValueError, KeyError):
                found.append(Event.from_wire(row))
        return found[-500:]

    def on_enabled(proposal: Proposal) -> None:
        if arena is not None:
            arena.mark_patched()

    def registry_for(domain: str) -> Any:
        return domains[domain].registry

    return AutopilotService(
        drafter=drafter,
        prover=ReplayProver(domains, traces, decisions=decisions),
        policies=PolicyGateway(policies),
        registry_for=registry_for,
        events=events,
        on_enabled=on_enabled,
    )


def breach_listener(
    autopilot: AutopilotService, arena: ArenaService, policies: PolicyService
) -> Callable[[Attempt, str], None]:
    """Arena breach of Guard or Full -> breach facts (enums only) -> an Autopilot proposal."""
    tasks: set[asyncio.Task[None]] = set()

    async def handle(attempt: Attempt, defender: str) -> None:
        domain = arena.domains[attempt.domain]
        result = attempt.defenders.get(defender) or attempt.defenders.get("naive")
        source = result if result is not None and result.trace else attempt.defenders.get("naive")
        if source is None or not source.trace:
            return
        trace = Trace(attempt.attempt_id, source.trace, "recorded", source.answer)
        trigger = ArenaTrigger(
            attempt.attempt_id, domain.name, attempt.goal_id, attempt.payload, trace
        )
        facts = await breach_facts(domain, trigger, lambda: policies.bundle, defender=defender)
        if facts.tool is None:
            return
        kind = "red_agent_breach" if attempt.source == "red_agent" else "arena_breach"
        await autopilot.submit(
            facts, trigger=kind, evidence_ids=[attempt.attempt_id], trigger_ref=trigger,
            breach_time=time.time(),
        )  # fmt: skip

    def listener(attempt: Attempt, defender: str) -> None:
        task = asyncio.create_task(handle(attempt, defender))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    return listener


class ManualIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: str = Field(max_length=64)
    defender: str = Field(default="guard", pattern="^(guard|full)$")


class EnableIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: str = Field(default="human:console", max_length=64, pattern=r"^[A-Za-z0-9:_.\- ]+$")


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    autonomous: bool


def _autopilot(request: Request) -> AutopilotService:
    autopilot = getattr(request.app.state, "autopilot", None)
    if autopilot is None:
        raise AutopilotError(503, "autopilot_unavailable", "Autopilot is not configured.")
    return autopilot


def _error(exc: AutopilotError) -> JSONResponse:
    return JSONResponse(
        {"error": exc.code, "message": exc.message, "details": {}}, status_code=exc.status
    )


def autopilot_router(require_admin: Callable[..., None]) -> APIRouter:
    router = APIRouter(prefix="/v1/autopilot", dependencies=[Depends(require_admin)])

    @router.get("/proposals")
    async def proposals(request: Request) -> dict[str, Any]:
        return {"proposals": [p.to_wire() for p in _autopilot(request).list()]}

    @router.get("/proposals/{proposal_id}")
    async def proposal(request: Request, proposal_id: str) -> JSONResponse:
        try:
            return JSONResponse(_autopilot(request).get(proposal_id).to_wire())
        except AutopilotError as exc:
            return _error(exc)

    @router.post("/proposals")
    async def manual(request: Request, body: ManualIn) -> JSONResponse:
        """Draft and prove a rule for an arena attempt (e.g. one the console points at)."""
        autopilot = _autopilot(request)
        arena: ArenaService | None = request.app.state.arena
        if arena is None or body.attempt_id not in arena.attempts:
            return _error(AutopilotError(404, "not_found", "no such arena attempt"))
        attempt = arena.attempts[body.attempt_id]
        naive = attempt.defenders.get("naive")
        if naive is None or not naive.trace:
            return _error(
                AutopilotError(409, "no_trace", "this attempt has no recorded tool calls")
            )
        domain = arena.domains[attempt.domain]
        trace = Trace(attempt.attempt_id, naive.trace, "recorded", naive.answer)
        trigger = ArenaTrigger(
            attempt.attempt_id, domain.name, attempt.goal_id, attempt.payload, trace
        )
        policies: PolicyService = request.app.state.policies
        facts: BreachFacts = await breach_facts(
            domain, trigger, lambda: policies.bundle, defender=body.defender
        )
        if facts.tool is None:
            return _error(
                AutopilotError(422, "no_breach", "replaying this attempt causes no breach")
            )
        created = await autopilot.propose(
            facts, trigger="manual", evidence_ids=[attempt.attempt_id], trigger_ref=trigger
        )
        return JSONResponse(created.to_wire(), status_code=201)

    @router.post("/proposals/{proposal_id}/enable")
    async def enable(
        request: Request, proposal_id: str, body: EnableIn | None = None
    ) -> JSONResponse:
        try:
            enabled = await _autopilot(request).enable(proposal_id, by=(body or EnableIn()).by)
        except AutopilotError as exc:
            return _error(exc)
        return JSONResponse(enabled.to_wire())

    @router.post("/proposals/{proposal_id}/reject")
    async def reject(request: Request, proposal_id: str) -> JSONResponse:
        try:
            return JSONResponse((await _autopilot(request).reject(proposal_id)).to_wire())
        except AutopilotError as exc:
            return _error(exc)

    @router.post("/proposals/{proposal_id}/rollback")
    async def rollback(request: Request, proposal_id: str) -> JSONResponse:
        try:
            return JSONResponse((await _autopilot(request).rollback(proposal_id)).to_wire())
        except AutopilotError as exc:
            return _error(exc)

    @router.get("/settings")
    async def get_settings(request: Request) -> dict[str, Any]:
        return {"autonomous": _autopilot(request).autonomous}

    @router.put("/settings")
    async def put_settings(request: Request, body: SettingsIn) -> dict[str, Any]:
        _autopilot(request).autonomous = body.autonomous
        return {"autonomous": body.autonomous}

    return router
