"""F05 Gate and Gate runtime. Spec: docs/features/F05-gate.md."""

import asyncio
import threading
import time

import pytest

from agentwall.core.contracts import Decision, Event, ToolCallRequest
from agentwall.core.labels import Confidentiality, untrusted
from agentwall.core.registry import Registry
from agentwall.engine.approvals import ApprovalNotPending, InProcessApprovalBroker
from agentwall.engine.gate import Gate, GateRuntime, ToolBlocked
from agentwall.engine.policy import PolicyBundle, compile_pack
from tests.engine._factories import PAY_PACK, arg, pay_spec, read_spec, request

TAINTED = untrusted("tool:read#R-102")


class Sink:
    """Collects events in memory."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> list[str]:
        return [event.kind for event in self.events]


class BrokenSink:
    def emit(self, event: Event) -> None:
        raise RuntimeError("event store is down")


def _registry() -> Registry:
    registry = Registry()
    registry.register(pay_spec())
    registry.register(read_spec())
    return registry


def _runtime(
    *packs: str,
    sink: object | None = None,
    broker: InProcessApprovalBroker | None = None,
    offline: bool = False,
    approval_timeout: float = 5.0,
) -> tuple[GateRuntime, Sink, InProcessApprovalBroker]:
    bundle = PolicyBundle(tuple(compile_pack(p) for p in packs))
    events = sink if sink is not None else Sink()
    approvals = broker or InProcessApprovalBroker()
    runtime = GateRuntime(
        Gate(_registry(), lambda: bundle),
        approvals,
        events,  # type: ignore[arg-type]
        offline=lambda: offline,
        approval_timeout=approval_timeout,
    )
    return runtime, events, approvals  # type: ignore[return-value]


def _mode_pack(mode: str) -> str:
    return f"schema_version: 1\npack: modes\nmodes: {{agent-a: {mode}}}\nrules: []\n"


async def _pay() -> str:
    return "paid"


BAD_PAY = request("pay", account=arg("ACC-1"), amount=arg(4999, bad=True))
ASK_PAY = request("pay", context=TAINTED, account=arg("ACC-1"), amount=arg(5000))
GOOD_PAY = request("pay", account=arg("ACC-1"), amount=arg(10))


# ---------------------------------------------------------------- enforce


async def test_allowed_call_executes_and_emits_one_event() -> None:
    runtime, sink, _ = _runtime()
    outcome = await runtime.enforce(GOOD_PAY, _pay)
    assert (outcome.executed, outcome.result, outcome.decision.kind) == (True, "paid", "allow")
    assert sink.kinds() == ["tool.call"]
    assert sink.events[0].outcome == "executed"


async def test_block_raises_without_executing_and_emits_one_event() -> None:
    runtime, sink, _ = _runtime()
    calls = []

    async def pay() -> None:
        calls.append(1)

    with pytest.raises(ToolBlocked) as blocked:
        await runtime.enforce(BAD_PAY, pay)
    assert blocked.value.decision.rule == "core/C1-untrusted-critical-arg"
    assert calls == []
    assert sink.kinds() == ["tool.call"]
    assert sink.events[0].outcome == "blocked"
    assert sink.events[0].decision is not None


async def test_monitor_mode_executes_and_marks_the_decision_not_enforced() -> None:
    runtime, sink, _ = _runtime(_mode_pack("monitor"))
    outcome = await runtime.enforce(BAD_PAY, _pay)
    assert outcome.executed
    assert (outcome.decision.kind, outcome.decision.enforced) == ("block", False)
    assert sink.events[0].outcome == "executed"


async def test_off_mode_executes_and_emits_nothing() -> None:
    runtime, sink, _ = _runtime(_mode_pack("off"))
    outcome = await runtime.enforce(BAD_PAY, _pay)
    assert outcome.executed
    assert sink.events == []


async def test_shadow_executes_everything_and_reports_the_would_be_decision() -> None:
    runtime, _, _ = _runtime()
    outcome = await runtime.enforce(BAD_PAY, _pay, shadow=True)
    assert outcome.executed
    assert (outcome.decision.kind, outcome.decision.enforced) == ("block", False)


# ---------------------------------------------------------------- approvals


async def _resolve_when_requested(
    broker: InProcessApprovalBroker, verdict: str, scope: str = "once"
) -> None:
    pending = await broker.next_pending()
    broker.resolve(pending.approval_id, verdict, scope)  # type: ignore[arg-type]


async def test_ask_waits_for_approval_then_executes() -> None:
    runtime, sink, broker = _runtime()
    approver = asyncio.create_task(_resolve_when_requested(broker, "approve"))
    outcome = await runtime.enforce(ASK_PAY, _pay)
    await approver
    assert outcome.executed
    assert sink.kinds() == ["approval.requested", "approval.resolved", "tool.call"]


async def test_a_denied_approval_blocks() -> None:
    runtime, _, broker = _runtime()
    approver = asyncio.create_task(_resolve_when_requested(broker, "deny"))
    with pytest.raises(ToolBlocked) as blocked:
        await runtime.enforce(ASK_PAY, _pay)
    await approver
    assert blocked.value.decision.rule == "runtime/approval-denied"
    assert "core/C3-untrusted-context-high-risk" in blocked.value.decision.matched


async def test_an_unanswered_approval_expires_and_blocks() -> None:
    runtime, _, broker = _runtime(approval_timeout=0.05)
    with pytest.raises(ToolBlocked) as blocked:
        await runtime.enforce(ASK_PAY, _pay)
    assert blocked.value.decision.rule == "runtime/approval-expired"
    assert broker.pending() == []


async def test_resolving_after_expiry_is_rejected() -> None:
    runtime, _, broker = _runtime(approval_timeout=0.05)
    seen: list[str] = []

    async def remember_id() -> None:
        seen.append((await broker.next_pending()).approval_id)

    watcher = asyncio.create_task(remember_id())
    with pytest.raises(ToolBlocked):
        await runtime.enforce(ASK_PAY, _pay)
    await watcher
    with pytest.raises(ApprovalNotPending):
        broker.resolve(seen[0], "approve", "once")


async def test_offline_turns_ask_into_block() -> None:
    runtime, _, broker = _runtime(offline=True)
    with pytest.raises(ToolBlocked) as blocked:
        await runtime.enforce(ASK_PAY, _pay)
    assert blocked.value.decision.rule == "runtime/offline-no-approver"
    assert broker.pending() == []


async def test_a_run_scoped_approval_is_reused_for_the_same_run_tool_and_rule() -> None:
    runtime, sink, broker = _runtime()
    approver = asyncio.create_task(_resolve_when_requested(broker, "approve", scope="run"))
    await runtime.enforce(ASK_PAY, _pay)
    await approver
    second = await runtime.enforce(ASK_PAY, _pay)  # no approver this time
    assert second.executed
    assert sink.kinds().count("approval.requested") == 1


async def test_a_broken_broker_is_treated_as_offline() -> None:
    class BrokenBroker(InProcessApprovalBroker):
        async def open(self, request: ToolCallRequest, decision: Decision) -> str:
            raise ConnectionError("approvals service unreachable")

    runtime, _, _ = _runtime(broker=BrokenBroker())
    with pytest.raises(ToolBlocked) as blocked:
        await runtime.enforce(ASK_PAY, _pay)
    assert blocked.value.decision.rule == "runtime/offline-no-approver"


async def test_a_named_pack_allow_needs_no_approval() -> None:
    runtime, sink, _ = _runtime(PAY_PACK)
    calm = request("pay", context=TAINTED, account=arg("ACC-1"), amount=arg(120))
    assert (await runtime.enforce(calm, _pay)).executed
    assert sink.kinds() == ["tool.call"]


# ---------------------------------------------------------------- events and errors


async def test_event_previews_redact_secrets() -> None:
    runtime, sink, _ = _runtime()
    secret = arg("AKIAIOSFODNN7EXAMPLE", conf=Confidentiality.SECRET)
    keyed = arg("token sk-abcdefghijklmnopqrstuvwxyz123456")
    call = request("pay", account=secret, amount=arg(10), note=keyed)
    with pytest.raises(ToolBlocked):  # secret to an internal audience: C2 blocks
        await runtime.enforce(call, _pay)
    previews = sink.events[0].args or {}
    assert previews["account"]["preview"] == "[secret · 20 chars]"
    assert "sk-abc" not in previews["note"]["preview"]


async def test_a_failing_event_sink_never_fails_the_call() -> None:
    runtime, _, _ = _runtime(sink=BrokenSink())
    outcome = await runtime.enforce(GOOD_PAY, _pay)
    assert outcome.executed
    assert runtime.dropped_events == 1


async def test_a_tool_error_is_recorded_and_raised() -> None:
    runtime, sink, _ = _runtime()

    async def broken() -> None:
        raise ValueError("upstream refused the request")

    with pytest.raises(ValueError, match="upstream refused"):
        await runtime.enforce(GOOD_PAY, broken)
    assert sink.events[0].outcome == "error"
    assert "upstream refused" in sink.events[0].data["error"]


async def test_sync_tools_run_off_the_event_loop() -> None:
    runtime, _, _ = _runtime()
    loop_thread = threading.get_ident()

    def sync_pay() -> int:
        return threading.get_ident()

    outcome = await runtime.enforce(GOOD_PAY, sync_pay)
    assert outcome.result != loop_thread


async def test_a_slow_tool_times_out_as_an_error() -> None:
    runtime, sink, _ = _runtime()
    runtime.tool_timeout = 0.05

    async def slow() -> None:
        await asyncio.sleep(5)

    with pytest.raises(TimeoutError):
        await runtime.enforce(GOOD_PAY, slow)
    assert sink.events[0].outcome == "error"


async def test_source_reads_are_allowed_and_still_emit_an_event() -> None:
    runtime, sink, _ = _runtime()
    outcome = await runtime.enforce(request("read", context=TAINTED, id=arg("R-1")), _pay)
    assert outcome.executed
    assert sink.kinds() == ["tool.call"]


def test_gate_check_is_pure_and_applies_monitor_mode() -> None:
    bundle = PolicyBundle((compile_pack(_mode_pack("monitor")),))
    decision = Gate(_registry(), lambda: bundle).check(BAD_PAY)
    assert (decision.kind, decision.enforced) == ("block", False)


# ---------------------------------------------------------------- performance


@pytest.mark.perf
async def test_runtime_overhead_p99_is_under_two_milliseconds() -> None:
    runtime, _, _ = _runtime(PAY_PACK)

    async def noop() -> None:
        return None

    timings = []
    for _ in range(2000):
        start = time.perf_counter()
        await runtime.enforce(GOOD_PAY, noop)
        timings.append(time.perf_counter() - start)
    p99 = sorted(timings)[int(len(timings) * 0.99)]
    print(f"\ngate runtime overhead p99: {p99 * 1e6:.0f} µs")
    assert p99 < 2e-3
