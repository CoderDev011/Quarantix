"""Shared request and decision types (docs/contracts.md sections 5 and 6).

These are fast, immutable in-process types holding F01 labels. `to_wire()` and
`from_wire()` convert to and from the contract's JSON shape, which is binding.
"""

from __future__ import annotations

import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from quarantix.core.labels import BOTTOM, Label

SCHEMA_VERSION = 1

Evidence = Literal["exact", "traced", "ambiguous", "inferred"]
Mode = Literal["full", "guard"]
DecisionKind = Literal["allow", "ask", "block"]

EventKind = Literal[
    "run.started",
    "plan.created",
    "plan.rejected",
    "tool.call",
    "limit",
    "answer.link_stripped",
    "run.finished",
    "approval.requested",
    "approval.resolved",
    "arena.result",
    "arena.breach",
    "autopilot.proposal",
    "autopilot.proof",
    "autopilot.enabled",
    "autopilot.rolled_back",
    "canary.result",
    "mcp.tool_pinned",
    "mcp.tool_changed",
    "mcp.description_flagged",
    "domain.generated",
    "proof.result",
    "policy.changed",
    "agent.mode_changed",
]
Outcome = Literal["executed", "blocked", "skipped", "error"]

EVIDENCE: frozenset[str] = frozenset(typing.get_args(Evidence))
EVENT_KINDS: frozenset[str] = frozenset(typing.get_args(EventKind))
OUTCOMES: frozenset[str] = frozenset(typing.get_args(Outcome))
MODES: frozenset[str] = frozenset(typing.get_args(Mode))
DECISION_KINDS: frozenset[str] = frozenset(typing.get_args(DecisionKind))
SEVERITY: Mapping[str, int] = {"allow": 0, "ask": 1, "block": 2}


@dataclass(frozen=True, slots=True)
class ArgValue:
    value: Any
    label: Label
    evidence: Evidence = "exact"
    node: str | None = None

    def __post_init__(self) -> None:
        if self.evidence not in EVIDENCE:
            raise ValueError(f"invalid evidence {self.evidence!r}")

    def to_wire(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "label": self.label.to_wire(),
            "evidence": self.evidence,
            "node": self.node,
        }

    @classmethod
    def from_wire(cls, wire: Mapping[str, Any]) -> ArgValue:
        return cls(
            wire["value"],
            Label.from_wire(wire["label"]),
            wire.get("evidence", "exact"),
            wire.get("node"),
        )


@dataclass(frozen=True, slots=True)
class ToolCallRequest:
    run_id: str
    agent: str
    mode: Mode
    tool: str
    args: Mapping[str, ArgValue]
    context: Label = BOTTOM
    step_id: str | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"invalid mode {self.mode!r}")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "agent": self.agent,
            "mode": self.mode,
            "step_id": self.step_id,
            "tool": self.tool,
            "args": {name: value.to_wire() for name, value in self.args.items()},
            "context": self.context.to_wire(),
        }

    @classmethod
    def from_wire(cls, wire: Mapping[str, Any]) -> ToolCallRequest:
        if wire.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema_version {wire.get('schema_version')!r}")
        return cls(
            run_id=wire["run_id"],
            agent=wire["agent"],
            mode=wire["mode"],
            tool=wire["tool"],
            args={name: ArgValue.from_wire(v) for name, v in wire["args"].items()},
            context=Label.from_wire(wire["context"]),
            step_id=wire.get("step_id"),
        )


@dataclass(frozen=True, slots=True)
class Decision:
    kind: DecisionKind
    rule: str
    reason: str
    policy_version: str
    offending_arg: str | None = None
    matched: tuple[str, ...] = ()
    provenance: Mapping[str, Any] | None = field(default=None, compare=False)
    enforced: bool = True

    def __post_init__(self) -> None:
        if self.kind not in DECISION_KINDS:
            raise ValueError(f"invalid decision kind {self.kind!r}")

    @property
    def severity(self) -> int:
        return SEVERITY[self.kind]

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "rule": self.rule,
            "reason": self.reason,
            "offending_arg": self.offending_arg,
            "matched": list(self.matched),
            "provenance": None if self.provenance is None else dict(self.provenance),
            "policy_version": self.policy_version,
            "enforced": self.enforced,
        }


@dataclass(frozen=True, slots=True)
class Event:
    """The record every component speaks (contracts section 7).

    `seq` is assigned by the control plane when the event is stored.
    """

    event_id: str
    run_id: str
    agent: str
    mode: Mode
    kind: EventKind
    time: datetime
    tool: str | None = None
    args: Mapping[str, Mapping[str, Any]] | None = None  # argument previews (contracts section 8)
    context: Label | None = None
    decision: Decision | None = None
    outcome: Outcome | None = None
    latency_ms: float | None = None
    data: Mapping[str, Any] = field(default_factory=dict)
    seq: int | None = None

    def __post_init__(self) -> None:
        if self.kind not in EVENT_KINDS:
            raise ValueError(f"invalid event kind {self.kind!r}")
        if self.mode not in MODES:
            raise ValueError(f"invalid mode {self.mode!r}")
        if self.outcome is not None and self.outcome not in OUTCOMES:
            raise ValueError(f"invalid outcome {self.outcome!r}")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "seq": self.seq,
            "event_id": self.event_id,
            "run_id": self.run_id,
            "agent": self.agent,
            "mode": self.mode,
            "kind": self.kind,
            "time": self.time.isoformat(),
            "tool": self.tool,
            "args": None if self.args is None else {k: dict(v) for k, v in self.args.items()},
            "context": None if self.context is None else self.context.to_wire(),
            "decision": None if self.decision is None else self.decision.to_wire(),
            "outcome": self.outcome,
            "latency_ms": self.latency_ms,
            "data": dict(self.data),
        }
