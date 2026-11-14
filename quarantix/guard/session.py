"""Guard session (F11): enforcement for an agent we did not write, with no plan.

One session per agent conversation (or MCP client connection). The session
observes the user's message, then every tool call goes through `call`:

1. Each argument is traced (F11 tracer). Unknown values take the session taint's
   integrity with evidence "inferred"; traced values keep their trace.
2. The request (mode "guard", context = the taint) goes through the Gate runtime,
   which blocks, asks or runs it and emits exactly one `tool.call` event.
3. The result is labeled from the tool spec, indexed, joined into the taint and
   added to the provenance graph (arguments link to the results they matched).

Shadow mode executes everything and records what would have been decided; the
first would-block (or would-ask) step is reported, which the arena uses.
"""

from __future__ import annotations

import inspect
import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from quarantix.core.contracts import ArgValue, Decision, Evidence, ToolCallRequest
from quarantix.core.labels import BOTTOM, Integrity, Label, join_all
from quarantix.core.provenance import ProvenanceGraph
from quarantix.core.registry import Registry, ToolSpec
from quarantix.engine.gate import GateRuntime
from quarantix.engine.policy import check_answer as policy_check_answer
from quarantix.guard.tracer import Trace, ValueTracer

USER_LABEL = Label(Integrity.TRUSTED, BOTTOM.confidentiality, frozenset({"user"}))
MAX_GRAPH_NODES = 5000


@dataclass(frozen=True, slots=True)
class WouldHave:
    """A decision shadow mode recorded instead of enforcing (allow decisions are not kept)."""

    call_index: int  # 1-based position of the call in this session
    tool: str
    decision: Decision


class GuardSession:
    def __init__(
        self,
        registry: Registry,
        runtime: GateRuntime,
        *,
        agent: str,
        run_id: str,
        shadow: bool = False,
        max_index_bytes: int = 5_000_000,
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.agent = agent
        self.run_id = run_id
        self.shadow = shadow
        self.taint: Label = BOTTOM
        self.graph = ProvenanceGraph()
        self.tracer = ValueTracer(max_bytes=max_index_bytes, on_evict=self._evicted)
        self.would_have: list[WouldHave] = []
        self.calls = 0
        self._step = itertools.count(1)

    # ---------------------------------------------------------------- inputs

    def observe_user(self, text: str) -> None:
        """The user's own message: trusted."""
        node = self._add("user", "user message", USER_LABEL)
        self.tracer.index_user(text, node=node)

    @property
    def first_would_block(self) -> WouldHave | None:
        return self.would_have[0] if self.would_have else None

    # ---------------------------------------------------------------- tool calls

    async def call(
        self,
        tool: str,
        args: Mapping[str, Any],
        invoke: Callable[[], Any] | None = None,
    ) -> Any:
        """Check and run one tool call. Raises ToolBlocked instead of running a blocked call."""
        spec = self.registry.get(tool)
        self.calls += 1
        step = f"g{next(self._step)}"
        traced = {name: self._argument(step, name, value) for name, value in args.items()}
        request = ToolCallRequest(
            run_id=self.run_id,
            agent=self.agent,
            mode="guard",
            tool=tool,
            args=traced,
            context=self.taint,
            step_id=step,
        )
        provenance = None
        if spec.kind != "source":
            sink_label = join_all(a.label for a in traced.values()).join(self.taint)
            parents = [a.node for a in traced.values() if a.node]
            sink = self._add("sink", tool, sink_label, parents)
            provenance = self.graph.explain(sink) if sink else None

        if invoke is None:
            invoke = _default_invoke(spec, args)
        outcome = await self.runtime.enforce(
            request, invoke, provenance=provenance, shadow=self.shadow
        )
        if self.shadow and outcome.decision.kind != "allow":
            self.would_have.append(WouldHave(self.calls, tool, outcome.decision))
        self._absorb(spec, outcome.result, traced)
        return outcome.result

    def check_answer(self, text: str) -> tuple[str, list[str]]:
        """C4: strip links to hosts outside the allow-list when the session saw untrusted data."""
        policy = self.runtime.gate.policy_for(self.agent)
        return policy_check_answer(text, self.taint, policy.allowed_link_hosts)

    # ---------------------------------------------------------------- internals

    def _argument(self, step: str, name: str, value: Any) -> ArgValue:
        trace = self.tracer.trace(value)
        evidence: Evidence
        if trace.evidence == "unknown":
            label = Label(self.taint.integrity, BOTTOM.confidentiality, self.taint.sources)
            evidence = "inferred"
        else:
            label = trace.label
            evidence = trace.evidence
        node = self._add("arg", f"{step}.{name}", label, _known(self.graph, trace))
        return ArgValue(value, label, evidence, node)

    def _absorb(self, spec: ToolSpec, result: Any, args: Mapping[str, ArgValue]) -> None:
        # Only arguments with trace evidence taint the result. An "inferred" label is just the
        # session taint, which still applies as the context; joining it into every field would
        # make our own records untrusted after any untrusted read (a false block found live).
        inputs = join_all(a.label for a in args.values() if a.evidence != "inferred")
        base = spec.output_label if spec.endorses_output else spec.output_label.join(inputs)
        tool_source = f"tool:{spec.name}"
        field_labels = spec.field_labels
        if not spec.endorses_output and field_labels:
            field_labels = {k: v.join(inputs) for k, v in field_labels.items()}
        parents = [a.node for a in args.values() if a.node]
        records = result if isinstance(result, list) else [result]
        labels: list[Label] = [base]
        for record in records[:1000]:
            record_id = record.get("id") if isinstance(record, Mapping) else None
            if isinstance(record, Mapping) and record_id is None:
                record_id = next(
                    (v for k, v in record.items() if k.endswith(("_id", "number", "name"))), None
                )
            source = f"{tool_source}#{record_id}" if record_id is not None else tool_source
            record_label = _with_source(base, source)
            fields = {k: _with_source(v, source) for k, v in field_labels.items()}
            title = f"{spec.name} {record_id}" if record_id is not None else spec.name
            label = (
                join_all([record_label, *fields.values()])
                if isinstance(record, Mapping)
                else record_label
            )
            node = self._add("tool", title, label, parents)
            self.tracer.index(
                record, record_label, endorsed=spec.endorses_output, node=node, field_labels=fields
            )
            labels.append(label)
        if spec.kind != "sink":
            self.taint = self.taint.join(join_all(labels))

    def _add(
        self, kind: str, title: str, label: Label, parents: list[str] | tuple[str, ...] = ()
    ) -> str:
        if len(self.graph) >= MAX_GRAPH_NODES:
            return ""
        return self.graph.add(kind, title, label, [p for p in parents if p])

    def _evicted(self, count: int) -> None:
        self.runtime.emit(
            "limit", run_id=self.run_id, agent=self.agent, mode="guard",
            data={"name": "guard_index_bytes", "evicted_results": count},
        )  # fmt: skip


def _known(graph: ProvenanceGraph, trace: Trace) -> list[str]:
    return [n for n in trace.nodes if n]


def _with_source(label: Label, source: str) -> Label:
    return replace(label, sources=frozenset({source}))


def _default_invoke(spec: ToolSpec, args: Mapping[str, Any]) -> Callable[[], Any]:
    fn = spec.fn
    if fn is None:
        raise LookupError(f"tool {spec.name!r} has no implementation; pass invoke")
    plain = dict(args)
    if inspect.iscoroutinefunction(fn):

        async def run_async() -> Any:
            return await fn(**plain)

        return run_async

    def run() -> Any:
        return fn(**plain)

    return run
