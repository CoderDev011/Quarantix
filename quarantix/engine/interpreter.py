"""Interpreter (F06): run a plan with exact label propagation (full mode).

The plan is fixed before any data is read, so untrusted text can only ever fill
values, never choose steps, tools or argument names. Every value carries a label
and a provenance node. Branches and loops on untrusted data raise the context
label, so control-flow steering is visible to the Gate. A blocked or failed step
marks its output unavailable, and only the steps that depend on it are skipped.
"""

from __future__ import annotations

import asyncio
import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from quarantix.core.contracts import ArgValue, ToolCallRequest
from quarantix.core.labels import BOTTOM, Confidentiality, Integrity, Label, Labeled, join_all
from quarantix.core.plan import Call, Extract, ForEach, Format, If, Plan, Ref, Return, Step
from quarantix.core.provenance import ProvenanceGraph
from quarantix.core.redact import scrub
from quarantix.core.registry import Registry, ToolSpec
from quarantix.engine.gate import GateRuntime, ToolBlocked
from quarantix.engine.policy import check_answer

PLANNER_LABEL = Label(Integrity.TRUSTED, Confidentiality.PUBLIC, frozenset({"planner"}))
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

Status = Literal["ok", "partial", "failed"]


class Reader(Protocol):
    """The quarantined reader (F08). Output fields carry the source's label."""

    async def extract(
        self, source: Labeled, fields: Mapping[str, str], graph: ProvenanceGraph, step_id: str
    ) -> Labeled: ...


@dataclass(frozen=True, slots=True)
class Limits:
    max_tool_calls: int = 100
    max_items: int = 50
    max_concurrency: int = 4
    wall_clock_s: float = 180.0


@dataclass(frozen=True, slots=True)
class RunContext:
    run_id: str
    agent: str
    limits: Limits = Limits()


@dataclass(slots=True)
class RunResult:
    status: Status
    answer: str | None
    answer_label: Label | None
    steps: dict[str, str]
    removed_links: list[str] = field(default_factory=list)
    graph: ProvenanceGraph | None = None


@dataclass(frozen=True, slots=True)
class _Unavailable:
    """Bound to a step's output when that step was blocked, failed or skipped."""

    step_id: str


class _Missing(Exception):
    """A reference that does not resolve (unknown name, field or index)."""


class _DependsOn(Exception):
    def __init__(self, step_id: str) -> None:
        super().__init__(step_id)
        self.step_id = step_id


Scope = dict[str, "Labeled | _Unavailable"]


async def run_plan(
    plan: Plan,
    *,
    registry: Registry,
    runtime: GateRuntime,
    reader: Reader,
    ctx: RunContext,
) -> RunResult:
    run = _Run(registry, runtime, reader, ctx)
    try:
        async with asyncio.timeout(ctx.limits.wall_clock_s):
            await run.steps(plan.steps, {}, BOTTOM, "")
    except TimeoutError:
        run.limit("wall_clock_s", ctx.limits.wall_clock_s)
    return run.result()


class _Run:
    def __init__(
        self, registry: Registry, runtime: GateRuntime, reader: Reader, ctx: RunContext
    ) -> None:
        self.registry = registry
        self.runtime = runtime
        self.reader = reader
        self.ctx = ctx
        self.graph = ProvenanceGraph()
        self.states: dict[str, str] = {}
        self.tool_calls = 0
        self.stopped = False
        self.answer: str | None = None
        self.answer_label: Label | None = None
        self.removed: list[str] = []

    # ---------------------------------------------------------------- results and events

    def result(self) -> RunResult:
        states = list(self.states.values())
        if states and all(state == "ok" for state in states):
            status: Status = "ok"
        elif any(state == "ok" for state in states):
            status = "partial"
        else:
            status = "failed"
        return RunResult(
            status, self.answer, self.answer_label, self.states, self.removed, self.graph
        )

    def limit(self, name: str, value: float, step: str | None = None) -> None:
        self.stopped = True
        self.runtime.emit(
            "limit", run_id=self.ctx.run_id, agent=self.ctx.agent, mode="full",
            data={"limit": name, "value": value, "step": step},
        )  # fmt: skip

    def skip(self, step: Step, suffix: str, dependency: str) -> None:
        """Mark a step, and every step nested inside it, as skipped."""
        self.states[f"{step.id}{suffix}"] = f"skipped: depends on {dependency}"
        nested: Sequence[Step] = ()
        if isinstance(step, If):
            nested = (*step.then, *step.else_)
        elif isinstance(step, ForEach):
            nested = step.body
        for child in nested:
            self.skip(child, suffix, dependency)

    # ---------------------------------------------------------------- execution

    async def steps(self, steps: Sequence[Step], scope: Scope, context: Label, suffix: str) -> None:
        for step in steps:
            if self.stopped:
                return
            try:
                await self.step(step, scope, context, suffix)
            except _DependsOn as dependency:
                self.skip(step, suffix, dependency.step_id)
                self._mark_unavailable(step, scope)
            except _Missing as missing:
                self.states[f"{step.id}{suffix}"] = f"error: {missing}"
                self._mark_unavailable(step, scope)

    @staticmethod
    def _mark_unavailable(step: Step, scope: Scope) -> None:
        out = getattr(step, "out", None)
        if out:
            scope[out] = _Unavailable(step.id)

    async def step(self, step: Step, scope: Scope, context: Label, suffix: str) -> None:
        key = f"{step.id}{suffix}"
        if isinstance(step, Call):
            await self.call(step, scope, context, key)
        elif isinstance(step, Extract):
            await self.extract(step, scope, context, key)
        elif isinstance(step, If):
            value = self.resolve(step.cond.ref, scope)
            self.states[key] = "ok"
            branch = (
                step.then if _test(value.plain(), step.cond.test, step.cond.value) else step.else_
            )
            await self.steps(branch, scope, context.join(value.label), suffix)
        elif isinstance(step, ForEach):
            await self.for_each(step, scope, context, suffix, key)
        elif isinstance(step, Format):
            values = {name: self.resolve(ref, scope) for name, ref in step.values.items()}
            unknown = sorted(set(_PLACEHOLDER.findall(step.template)) - values.keys())
            if unknown:
                raise _Missing(f"template placeholders without values: {unknown}")
            text = _PLACEHOLDER.sub(lambda m: _render(values[m.group(1)].plain()), step.template)
            label = join_all(v.label for v in values.values()).join(context)
            node = self.graph.add("format", key, label, [v.node for v in values.values()])
            scope[step.out] = Labeled(text, label, node)
            self.states[key] = "ok"
        elif isinstance(step, Return):
            self.give_answer(step, scope, context, key)

    async def call(self, step: Call, scope: Scope, context: Label, key: str) -> None:
        spec = self.registry.get(step.tool)
        args = {
            name: self.argument(value, scope, f"{key}.{name}") for name, value in step.args.items()
        }
        self.tool_calls += 1
        if self.tool_calls > self.ctx.limits.max_tool_calls:
            self.states[key] = f"error: tool-call limit ({self.ctx.limits.max_tool_calls}) reached"
            self._mark_unavailable(step, scope)
            self.limit("max_tool_calls", self.ctx.limits.max_tool_calls, key)
            return
        if spec.fn is None:
            raise _Missing(f"tool {step.tool!r} has no implementation")

        request = ToolCallRequest(
            run_id=self.ctx.run_id,
            agent=self.ctx.agent,
            mode="full",
            tool=step.tool,
            args={n: ArgValue(a.plain(), a.label, "exact", a.node) for n, a in args.items()},
            context=context,
            step_id=key,
        )
        provenance = None
        if spec.kind != "source":  # the data path into this action, for the console graph
            sink_label = join_all(a.label for a in args.values()).join(context)
            sink = self.graph.add("sink", step.tool, sink_label, [a.node for a in args.values()])
            provenance = self.graph.explain(sink)

        invoke = functools.partial(spec.fn, **{n: a.plain() for n, a in args.items()})
        try:
            outcome = await self.runtime.enforce(request, invoke, provenance=provenance)
        except ToolBlocked:
            self.states[key] = "blocked"
            self._mark_unavailable(step, scope)
            return
        except Exception as exc:
            message, _ = scrub(f"{type(exc).__name__}: {exc}")
            self.states[key] = f"error: {message[:160]}"
            self._mark_unavailable(step, scope)
            return
        if step.out:
            scope[step.out] = self.label_result(spec, outcome.result, args, context)
        self.states[key] = "ok"

    async def extract(self, step: Extract, scope: Scope, context: Label, key: str) -> None:
        source = self.resolve(step.source, scope)
        if not isinstance(source.value, str):
            raise _Missing(f"extract source {step.source} is not text")
        try:
            result = await self.reader.extract(source, step.fields, self.graph, key)
        except Exception as exc:
            message, _ = scrub(f"{type(exc).__name__}: {exc}")
            self.states[key] = f"error: {message[:160]}"
            self._mark_unavailable(step, scope)
            return
        scope[step.out] = _join_tree(result, context)  # values read inside a branch carry it
        self.states[key] = "ok"

    async def for_each(
        self, step: ForEach, scope: Scope, context: Label, suffix: str, key: str
    ) -> None:
        items = self.resolve(step.items, scope)
        if not isinstance(items.value, list):
            raise _Missing(f"for_each items {step.items} is not a list")
        elements: list[Labeled] = items.value
        if len(elements) > self.ctx.limits.max_items:
            self.runtime.emit(
                "limit", run_id=self.ctx.run_id, agent=self.ctx.agent, mode="full",
                data={"limit": "max_items", "value": self.ctx.limits.max_items,
                      "step": key, "items": len(elements)},
            )  # fmt: skip
            elements = elements[: self.ctx.limits.max_items]
        self.states[key] = "ok"
        loop_context = context.join(items.label)
        semaphore = asyncio.Semaphore(self.ctx.limits.max_concurrency)

        async def iteration(index: int, element: Labeled) -> Labeled | None:
            async with semaphore:
                child: Scope = dict(scope)  # writes inside an iteration never leak out
                child[step.as_] = Labeled(
                    element.value, element.label.join(items.label), element.node
                )
                await self.steps(step.body, child, loop_context, f"{suffix}[{index}]")
                if step.collect is None:
                    return None
                try:
                    return self.resolve(step.collect, child)
                except (_Missing, _DependsOn):
                    return None  # nothing to collect from this iteration

        collected = [
            value
            for value in await asyncio.gather(*(iteration(i, e) for i, e in enumerate(elements)))
            if value is not None
        ]
        if step.out:
            label = join_all(v.label for v in collected).join(items.label)
            node = self.graph.add("format", f"{key} collect", label, [v.node for v in collected])
            scope[step.out] = Labeled(collected, label, node)

    def give_answer(self, step: Return, scope: Scope, context: Label, key: str) -> None:
        if isinstance(step.value, Ref):
            value = self.resolve(step.value, scope)
            text, label = _render(value.plain()), value.label.join(context)
        else:
            text, label = step.value, PLANNER_LABEL.join(context)
        hosts = self.runtime.gate.policy_for(self.ctx.agent).allowed_link_hosts
        clean, removed = check_answer(text, label, hosts)
        for url in removed:
            self.runtime.emit(
                "answer.link_stripped", run_id=self.ctx.run_id, agent=self.ctx.agent,
                mode="full", data={"step": key, "url_preview": scrub(url)[0][:60]},
            )  # fmt: skip
        self.answer, self.answer_label = clean, label
        self.removed.extend(removed)
        self.states[key] = "ok"
        self.stopped = True

    # ---------------------------------------------------------------- values

    def argument(self, value: Any, scope: Scope, title: str) -> Labeled:
        if isinstance(value, Ref):
            return self.resolve(value, scope)
        return Labeled(value, PLANNER_LABEL, self.graph.add("planner", title, PLANNER_LABEL))

    def resolve(self, ref: Ref, scope: Scope) -> Labeled:
        bound = scope.get(ref.root)
        if bound is None:
            raise _Missing(f"unknown reference {ref}")
        if isinstance(bound, _Unavailable):
            raise _DependsOn(bound.step_id)
        value = bound
        for part in ref.path:
            try:
                if isinstance(part, int):
                    child: Labeled = value.value[part]
                    value = Labeled(child.value, child.label.join(value.label), child.node)
                else:
                    value = value.field(part)
            except (KeyError, IndexError, TypeError):
                raise _Missing(f"reference {ref} does not resolve") from None
        return value

    def label_result(
        self, spec: ToolSpec, value: Any, args: Mapping[str, Labeled], context: Label
    ) -> Labeled:
        """Wrap a tool result in labels (contracts section 3 and F06 "Tool results")."""
        tool_source = f"tool:{spec.name}"
        inputs = join_all(a.label for a in args.values()).join(context)
        base = spec.output_label if spec.endorses_output else spec.output_label.join(inputs)
        result_node = self.graph.add(
            "tool",
            spec.name,
            _with_source(base, tool_source, tool_source),
            [a.node for a in args.values()],
        )

        def field_label(name: str, record_label: Label, source: str) -> Label | None:
            override = spec.field_labels.get(name)
            if override is None:
                return None
            label = override if spec.endorses_output else override.join(inputs)
            return _with_source(label, source, tool_source)

        def record(item: Mapping[str, Any]) -> Labeled:
            record_id = item.get("id")
            source = (
                f"{tool_source}#{record_id}" if isinstance(record_id, str | int) else tool_source
            )
            record_label = _with_source(base, source, tool_source)
            fields: dict[str, Labeled] = {}
            for name, child in item.items():
                override = field_label(name, record_label, source)
                if override is None:
                    fields[name] = _wrap(child, record_label, result_node)
                else:
                    title = (
                        f"{spec.name} {record_id}.{name}"
                        if record_id is not None
                        else f"{spec.name}.{name}"
                    )
                    fields[name] = _wrap(
                        child, override, self.graph.add("tool", title, override, [result_node])
                    )
            return Labeled(fields, record_label, result_node)

        top_label = _with_source(base, tool_source, tool_source)
        if isinstance(value, Mapping):
            return record(value)
        if isinstance(value, list):
            items = [
                record(item) if isinstance(item, Mapping) else _wrap(item, top_label, result_node)
                for item in value
            ]
            return Labeled(items, top_label, result_node)
        return Labeled(value, top_label, result_node)


# ---------------------------------------------------------------- helpers


def _with_source(label: Label, source: str, tool_source: str) -> Label:
    sources = (label.sources - {tool_source}) | {source}
    return Label(label.integrity, label.confidentiality, frozenset(sources))


def _wrap(value: Any, label: Label, node: str) -> Labeled:
    """Label a plain value, recursively, with one label."""
    if isinstance(value, Labeled):
        return value
    if isinstance(value, Mapping):
        return Labeled({k: _wrap(v, label, node) for k, v in value.items()}, label, node)
    if isinstance(value, list):
        return Labeled([_wrap(v, label, node) for v in value], label, node)
    return Labeled(value, label, node)


def _join_tree(value: Labeled, context: Label) -> Labeled:
    """Join `context` into a labeled tree (a no-op when the context adds nothing)."""
    label = value.label.join(context)
    inner = value.value
    if isinstance(inner, Mapping):
        inner = {k: _join_tree(v, context) for k, v in inner.items()}
    elif isinstance(inner, list):
        inner = [_join_tree(v, context) for v in inner]
    if label is value.label and inner is value.value:
        return value
    return Labeled(inner, label, value.node)


def _render(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(_render(item) for item in value)
    return str(value)


def _test(value: Any, test: str, operand: Any) -> bool:
    try:
        if test == "truthy":
            return bool(value)
        if test == "eq":
            return value == operand
        if test == "ne":
            return value != operand
        if test == "lt":
            return value < operand
        if test == "le":
            return value <= operand
        if test == "gt":
            return value > operand
        if test == "ge":
            return value >= operand
        if test == "in":
            return value in operand
    except TypeError:
        return False
    return False
