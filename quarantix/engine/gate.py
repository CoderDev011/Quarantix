"""Gate and Gate runtime (F05): the one enforcement point every way in uses.

`Gate.check` is pure: request -> decision, with the agent's mode applied.
`GateRuntime.enforce` wraps the real tool call: check, wait for a person on
"ask", never execute on "block", and emit exactly one `tool.call` event per call
after the outcome is known (approval events are separate). Modes:
enforce applies decisions, monitor logs them with enforced=False and executes,
off skips checking entirely and emits nothing (the true baseline).
"""

from __future__ import annotations

import asyncio
import inspect
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from agentwall.core.contracts import Decision, Event, EventKind, Outcome, ToolCallRequest
from agentwall.core.redact import preview, scrub
from agentwall.core.registry import RecordLookup, Registry
from agentwall.engine.approvals import ApprovalBroker, ApprovalResult
from agentwall.engine.policy import AgentPolicy, PolicyBundle, evaluate

OFFLINE_RULE = "runtime/offline-no-approver"
DENIED_RULE = "runtime/approval-denied"
EXPIRED_RULE = "runtime/approval-expired"
MODE_OFF_RULE = "runtime/mode-off"


class EventSink(Protocol):
    def emit(self, event: Event) -> None: ...


class ToolBlocked(Exception):
    """Raised instead of executing a blocked, denied or expired call."""

    def __init__(self, decision: Decision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    decision: Decision
    executed: bool
    result: Any
    latency_ms: float


class Gate:
    """Pure decisions. The policy source returns the current bundle (it may be swapped live)."""

    def __init__(
        self,
        registry: Registry,
        policy_source: Callable[[], PolicyBundle],
        record_lookup: RecordLookup | None = None,
    ) -> None:
        self.registry = registry
        self._policy_source = policy_source
        self._record_lookup = record_lookup

    def policy_for(self, agent: str) -> AgentPolicy:
        return self._policy_source().for_agent(agent)

    def check(self, request: ToolCallRequest, policy: AgentPolicy | None = None) -> Decision:
        policy = policy or self.policy_for(request.agent)
        decision = evaluate(request, self.registry.get(request.tool), policy, self._record_lookup)
        return replace(decision, enforced=False) if policy.mode == "monitor" else decision


class GateRuntime:
    def __init__(
        self,
        gate: Gate,
        approvals: ApprovalBroker,
        events: EventSink,
        *,
        offline: Callable[[], bool] = lambda: False,
        approval_timeout: float = 120.0,
        tool_timeout: float = 10.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self.gate = gate
        self.approvals = approvals
        self.events = events
        self.offline = offline
        self.approval_timeout = approval_timeout
        self.tool_timeout = tool_timeout
        self._clock = clock
        self._new_id = new_id
        self._run_approvals: set[tuple[str, str, str]] = set()
        self.dropped_events = 0

    async def enforce(
        self,
        request: ToolCallRequest,
        invoke: Callable[[], Any],
        *,
        provenance: Mapping[str, Any] | None = None,
        shadow: bool = False,
    ) -> ToolOutcome:
        """Check and (maybe) run one tool call. Raises ToolBlocked instead of running it.

        `invoke` takes no arguments and may be sync (run in a worker thread) or async.
        `shadow=True` always executes and reports the decision as "would have".
        """
        policy = self.gate.policy_for(request.agent)
        if policy.mode == "off" and not shadow:
            result, latency = await self._invoke(invoke)
            off = Decision(
                "allow", MODE_OFF_RULE, "Protection is off for this agent.", policy.version,
                enforced=False,
            )  # fmt: skip
            return ToolOutcome(off, True, result, latency)

        decision = self.gate.check(request, policy)
        if provenance is not None:
            decision = replace(decision, provenance=provenance)
        if shadow:
            decision = replace(decision, enforced=False)
        previews = {name: preview(a.value, a.label, a.evidence) for name, a in request.args.items()}

        if decision.enforced and decision.kind == "ask":
            decision = await self._ask_a_person(request, decision, previews)
        if decision.enforced and decision.kind == "block":
            self._emit("tool.call", request, previews, decision=decision, outcome="blocked")
            raise ToolBlocked(decision)

        try:
            result, latency = await self._invoke(invoke)
        except Exception as exc:
            message, _ = scrub(f"{type(exc).__name__}: {exc}")
            self._emit(
                "tool.call", request, previews, decision=decision, outcome="error",
                data={"error": message[:200]},
            )  # fmt: skip
            raise
        self._emit(
            "tool.call", request, previews, decision=decision, outcome="executed", latency=latency
        )
        return ToolOutcome(decision, True, result, latency)

    # ---------------------------------------------------------------- approvals

    async def _ask_a_person(
        self, request: ToolCallRequest, decision: Decision, previews: dict[str, Any]
    ) -> Decision:
        key = (request.run_id, request.tool, decision.rule)
        if key in self._run_approvals:
            return decision  # approved earlier "for this run"
        if self.offline():
            return _blocked_from(decision, OFFLINE_RULE, "No approver is reachable")
        try:
            approval_id = await self.approvals.open(request, decision)
        except Exception:  # an unreachable approvals service means offline
            return _blocked_from(decision, OFFLINE_RULE, "No approver is reachable")

        self._emit(
            "approval.requested", request, previews, decision=decision,
            data={"approval_id": approval_id, "rule": decision.rule, "reason": decision.reason},
        )  # fmt: skip
        try:
            result = await self.approvals.wait(approval_id, self.approval_timeout)
        except Exception:
            result = ApprovalResult("expired")
        self._emit(
            "approval.resolved", request, previews, decision=decision,
            data={"approval_id": approval_id, "status": result.status, "scope": result.scope},
        )  # fmt: skip

        if result.status == "approved":
            if result.scope == "run":
                self._run_approvals.add(key)
            return decision
        if result.status == "denied":
            return _blocked_from(decision, DENIED_RULE, "A person denied this call")
        return _blocked_from(decision, EXPIRED_RULE, "Nobody approved this call in time")

    # ---------------------------------------------------------------- helpers

    async def _invoke(self, invoke: Callable[[], Any]) -> tuple[Any, float]:
        async def call() -> Any:
            if inspect.iscoroutinefunction(invoke):
                return await invoke()
            value = await asyncio.to_thread(invoke)  # never block the event loop
            return await value if inspect.isawaitable(value) else value

        start = time.perf_counter()
        result = await asyncio.wait_for(call(), self.tool_timeout)
        return result, (time.perf_counter() - start) * 1000

    def _emit(
        self,
        kind: EventKind,
        request: ToolCallRequest,
        previews: Mapping[str, Any],
        *,
        decision: Decision | None = None,
        outcome: Outcome | None = None,
        latency: float | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        try:
            self.events.emit(
                Event(
                    event_id=self._new_id(),
                    run_id=request.run_id,
                    agent=request.agent,
                    mode=request.mode,
                    kind=kind,
                    time=self._clock(),
                    tool=request.tool,
                    args=previews,
                    context=request.context,
                    decision=decision,
                    outcome=outcome,
                    latency_ms=latency,
                    data=data or {},
                )
            )
        except Exception:  # an event sink failure must never fail the tool call
            self.dropped_events += 1


def _blocked_from(decision: Decision, rule: str, why: str) -> Decision:
    return Decision(
        kind="block",
        rule=rule,
        reason=f"{why}: {decision.reason}",
        policy_version=decision.policy_version,
        offending_arg=decision.offending_arg,
        matched=tuple(dict.fromkeys((*decision.matched, decision.rule))),
        provenance=decision.provenance,
        enforced=True,
    )
