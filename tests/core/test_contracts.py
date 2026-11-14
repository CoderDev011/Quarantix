"""Shared request/decision types. Spec: docs/contracts.md sections 5 and 6."""

from datetime import UTC, datetime

import pytest

from agentwall.core.contracts import ArgValue, Decision, Event, ToolCallRequest
from agentwall.core.labels import Confidentiality, trusted, untrusted


def _request() -> ToolCallRequest:
    return ToolCallRequest(
        run_id="r1",
        agent="agent-a",
        mode="guard",
        tool="pay",
        args={
            "amount": ArgValue(4999.0, untrusted("tool:list#T-2"), "traced", "n4"),
            "account": ArgValue("ACC-1", trusted("system", Confidentiality.PRIVATE)),
        },
        context=untrusted("tool:list#T-2"),
        step_id="s7",
    )


def test_request_round_trips_through_the_wire_format() -> None:
    request = _request()
    assert ToolCallRequest.from_wire(request.to_wire()) == request


def test_request_wire_format_matches_the_contract() -> None:
    wire = _request().to_wire()
    assert wire["schema_version"] == 1
    assert set(wire) == {
        "schema_version", "run_id", "agent", "mode", "step_id", "tool", "args", "context",
    }  # fmt: skip
    assert wire["args"]["amount"] == {
        "value": 4999.0,
        "label": {
            "integrity": "untrusted",
            "confidentiality": "internal",
            "sources": ["tool:list#T-2"],
        },
        "evidence": "traced",
        "node": "n4",
    }


def test_argument_evidence_defaults_to_exact() -> None:
    assert ArgValue(1, trusted("user")).evidence == "exact"


def test_invalid_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="evidence"):
        ArgValue(1, trusted("user"), "guessed")  # type: ignore[arg-type]


def test_invalid_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="mode"):
        ToolCallRequest(run_id="r", agent="a", mode="yolo", tool="t", args={})  # type: ignore[arg-type]


def test_decision_wire_format_matches_the_contract() -> None:
    decision = Decision(
        kind="block",
        rule="core/C1-untrusted-critical-arg",
        reason="The amount came from untrusted text.",
        policy_version="abc123def456",
        offending_arg="amount",
        matched=("core/C1-untrusted-critical-arg",),
    )
    assert decision.to_wire() == {
        "kind": "block",
        "rule": "core/C1-untrusted-critical-arg",
        "reason": "The amount came from untrusted text.",
        "offending_arg": "amount",
        "matched": ["core/C1-untrusted-critical-arg"],
        "provenance": None,
        "policy_version": "abc123def456",
        "enforced": True,
    }


def test_event_wire_format_matches_the_contract() -> None:
    event = Event(
        event_id="e1",
        run_id="r1",
        agent="agent-a",
        mode="guard",
        kind="tool.call",
        time=datetime(2026, 11, 14, 12, 0, tzinfo=UTC),
        tool="pay",
        outcome="blocked",
        latency_ms=1.5,
    )
    wire = event.to_wire()
    assert set(wire) == {
        "schema_version", "seq", "event_id", "run_id", "agent", "mode", "kind", "time",
        "tool", "args", "context", "decision", "outcome", "latency_ms", "data",
    }  # fmt: skip
    assert wire["schema_version"] == 1
    assert wire["seq"] is None
    assert wire["time"] == "2026-11-14T12:00:00+00:00"


def test_invalid_event_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        Event(
            event_id="e", run_id="r", agent="a", mode="guard", kind="party",  # type: ignore[arg-type]
            time=datetime(2026, 1, 1, tzinfo=UTC),
        )  # fmt: skip


def test_invalid_decision_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        Decision(kind="maybe", rule="r", reason="x", policy_version="v")  # type: ignore[arg-type]
