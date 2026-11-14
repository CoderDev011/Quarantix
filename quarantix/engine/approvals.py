"""Approval brokers (F05): where an "ask" decision waits for a person.

The broker interface is two steps, so the runtime can announce the approval
before waiting on it: `open` registers the request and returns its id, and
`wait` blocks until a person resolves it or the timeout expires. The in-process
broker lives inside the API; the SDK's HTTP broker (F12) implements the same
interface over POST + long-poll.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from agentwall.core.contracts import Decision, ToolCallRequest

Verdict = Literal["approve", "deny"]
Scope = Literal["once", "run"]
Status = Literal["approved", "denied", "expired"]


class ApprovalNotPending(LookupError):
    """The approval does not exist, was already resolved, or has expired (API: 409)."""


@dataclass(frozen=True, slots=True)
class ApprovalResult:
    status: Status
    scope: Scope = "once"


class ApprovalBroker(Protocol):
    async def open(self, request: ToolCallRequest, decision: Decision) -> str: ...

    async def wait(self, approval_id: str, max_wait: float) -> ApprovalResult: ...


@dataclass(slots=True)
class PendingApproval:
    approval_id: str
    request: ToolCallRequest
    decision: Decision
    created: float
    future: asyncio.Future[ApprovalResult] = field(repr=False)


class InProcessApprovalBroker:
    def __init__(self, new_id: Callable[[], str] = lambda: uuid.uuid4().hex) -> None:
        self._new_id = new_id
        self._pending: dict[str, PendingApproval] = {}
        self._opened = asyncio.Event()

    async def open(self, request: ToolCallRequest, decision: Decision) -> str:
        approval_id = self._new_id()
        future: asyncio.Future[ApprovalResult] = asyncio.get_running_loop().create_future()
        self._pending[approval_id] = PendingApproval(
            approval_id, request, decision, time.monotonic(), future
        )
        self._opened.set()
        return approval_id

    async def wait(self, approval_id: str, max_wait: float) -> ApprovalResult:
        pending = self._pending.get(approval_id)
        if pending is None:
            raise ApprovalNotPending(approval_id)
        try:
            async with asyncio.timeout(max_wait):
                return await asyncio.shield(pending.future)
        except TimeoutError:
            return ApprovalResult("expired")
        finally:
            self._pending.pop(approval_id, None)

    def resolve(self, approval_id: str, verdict: Verdict, scope: Scope = "once") -> None:
        if verdict not in ("approve", "deny"):
            raise ValueError(f"invalid verdict {verdict!r}")
        if scope not in ("once", "run"):
            raise ValueError(f"invalid scope {scope!r}")
        pending = self._pending.get(approval_id)
        if pending is None or pending.future.done():
            raise ApprovalNotPending(approval_id)
        status: Status = "approved" if verdict == "approve" else "denied"
        pending.future.set_result(ApprovalResult(status, scope))

    def pending(self) -> list[PendingApproval]:
        return sorted(self._pending.values(), key=lambda item: item.created)

    async def next_pending(self) -> PendingApproval:
        """Wait until an approval is pending and return the oldest (for inboxes and tests)."""
        while True:
            items = self.pending()
            if items:
                return items[0]
            self._opened.clear()
            await self._opened.wait()
