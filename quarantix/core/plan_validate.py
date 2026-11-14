"""Plan validator (F09, the MUST part): static checks before a plan ever runs.

Passes run in order; validation stops at the first pass that finds problems and
returns all of that pass's errors (so a planner gets one coherent batch to fix):
  1 tools exist · 2 argument names · 3 literal types · 4 references in scope ·
  5 extract field types · 6 size limits · 7 format placeholders · 8 a return step
Pure: no I/O. Used for pinned plans (F03), generated domains (F19) and the planner.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from quarantix.core.fieldtypes import parse_field_type
from quarantix.core.plan import Call, Extract, ForEach, Format, If, Plan, Ref, Return, Step
from quarantix.core.registry import Registry

_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class PlanLimits:
    max_steps: int = 40
    max_depth: int = 3


@dataclass(frozen=True, slots=True)
class PlanIssue:
    step_id: str | None
    message: str

    def __str__(self) -> str:
        return f"step {self.step_id}: {self.message}" if self.step_id else self.message


def validate_plan(
    plan: Plan, registry: Registry, limits: PlanLimits = PlanLimits()
) -> list[PlanIssue]:
    passes: tuple[Callable[[Plan, Registry, PlanLimits], list[PlanIssue]], ...] = (
        _tools_exist,
        _argument_names,
        _literal_types,
        _references_in_scope,
        _field_types,
        _size_limits,
        _format_placeholders,
        _has_return,
    )
    for check in passes:
        issues = check(plan, registry, limits)
        if issues:
            return issues
    return []


def _walk(steps: Sequence[Step], depth: int = 0) -> Iterator[tuple[Step, int]]:
    for step in steps:
        yield step, depth
        if isinstance(step, If):
            yield from _walk((*step.then, *step.else_), depth + 1)
        elif isinstance(step, ForEach):
            yield from _walk(step.body, depth + 1)


def _calls(plan: Plan) -> Iterator[Call]:
    return (step for step, _ in _walk(plan.steps) if isinstance(step, Call))


# ---------------------------------------------------------------- passes 1-3: tools and arguments


def _tools_exist(plan: Plan, registry: Registry, _limits: PlanLimits) -> list[PlanIssue]:
    return [
        PlanIssue(c.id, f"unknown tool {c.tool!r}") for c in _calls(plan) if c.tool not in registry
    ]


def _argument_names(plan: Plan, registry: Registry, _limits: PlanLimits) -> list[PlanIssue]:
    issues = []
    for call in _calls(plan):
        schema = registry.get(call.tool).arg_schema
        known = set(schema.get("properties", {}))
        for name in sorted(set(call.args) - known):
            issues.append(PlanIssue(call.id, f"unknown argument {name!r} for {call.tool}"))
        for name in sorted(set(schema.get("required", ())) - set(call.args)):
            issues.append(PlanIssue(call.id, f"missing required argument {name!r} for {call.tool}"))
    return issues


_JSON_TYPES: dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, int | float) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "text"
    return "integer" if isinstance(value, int) else "number"


def _allowed_types(property_schema: dict[str, Any]) -> list[str]:
    if "type" in property_schema:
        kind = property_schema["type"]
        return list(kind) if isinstance(kind, list) else [kind]
    return [
        s["type"] for s in property_schema.get("anyOf", ()) if isinstance(s, dict) and "type" in s
    ]


def _literal_types(plan: Plan, registry: Registry, _limits: PlanLimits) -> list[PlanIssue]:
    issues = []
    for call in _calls(plan):
        properties = registry.get(call.tool).arg_schema.get("properties", {})
        for name, value in call.args.items():
            if isinstance(value, Ref) or name not in properties:
                continue
            allowed = [t for t in _allowed_types(properties[name]) if t in _JSON_TYPES]
            if allowed and not any(_JSON_TYPES[t](value) for t in allowed):
                issues.append(
                    PlanIssue(
                        call.id,
                        f"argument {name!r} of {call.tool} must be {' or '.join(allowed)}, "
                        f"got {_type_name(value)}",
                    )
                )
    return issues


# ---------------------------------------------------------------- pass 4: references in scope


def _references_in_scope(plan: Plan, _registry: Registry, _limits: PlanLimits) -> list[PlanIssue]:
    issues: list[PlanIssue] = []

    def check(step_id: str, refs: Sequence[Ref], defined: set[str]) -> None:
        seen = set()
        for ref in refs:
            if ref.root not in defined and str(ref) not in seen:
                seen.add(str(ref))
                issues.append(
                    PlanIssue(step_id, f"reference {ref} is not defined before this step")
                )

    def block(steps: Sequence[Step], defined: set[str]) -> set[str]:
        for step in steps:
            if isinstance(step, Call):
                check(step.id, [v for v in step.args.values() if isinstance(v, Ref)], defined)
                if step.out:
                    defined.add(step.out)
            elif isinstance(step, Extract):
                check(step.id, [step.source], defined)
                defined.add(step.out)
            elif isinstance(step, Format):
                check(step.id, list(step.values.values()), defined)
                defined.add(step.out)
            elif isinstance(step, Return):
                if isinstance(step.value, Ref):
                    check(step.id, [step.value], defined)
            elif isinstance(step, If):
                check(step.id, [step.cond.ref], defined)
                # Values bound in either branch are visible after the if (branches share the scope).
                defined |= block(step.then, set(defined)) | block(step.else_, set(defined))
            elif isinstance(step, ForEach):
                check(step.id, [step.items], defined)
                inner = block(step.body, {*defined, step.as_})
                if step.collect is not None:
                    check(step.id, [step.collect], inner)
                if step.out:
                    defined.add(step.out)  # nothing else leaves the loop
        return defined

    block(plan.steps, set())
    return issues


# ---------------------------------------------------------------- passes 5-8


def _field_types(plan: Plan, _registry: Registry, _limits: PlanLimits) -> list[PlanIssue]:
    issues = []
    for step, _ in _walk(plan.steps):
        if isinstance(step, Extract):
            for name, spec in step.fields.items():
                try:
                    parse_field_type(spec)
                except ValueError:
                    issues.append(PlanIssue(step.id, f"field {name!r} has an invalid type: {spec}"))
    return issues


def _size_limits(plan: Plan, _registry: Registry, limits: PlanLimits) -> list[PlanIssue]:
    walked = list(_walk(plan.steps))
    issues = []
    if len(walked) > limits.max_steps:
        issues.append(
            PlanIssue(None, f"plan has {len(walked)} steps; the limit is {limits.max_steps}")
        )
    depth = max((d for _, d in walked), default=0)
    if depth > limits.max_depth:
        issues.append(
            PlanIssue(None, f"plan nesting depth is {depth}; the limit is {limits.max_depth}")
        )
    return issues


def _format_placeholders(plan: Plan, _registry: Registry, _limits: PlanLimits) -> list[PlanIssue]:
    issues = []
    for step, _ in _walk(plan.steps):
        if isinstance(step, Format):
            placeholders = sorted(set(_PLACEHOLDER.findall(step.template)))
            values = sorted(step.values)
            if placeholders != values:
                issues.append(
                    PlanIssue(
                        step.id,
                        f"template placeholders {placeholders} do not match values {values}",
                    )
                )
    return issues


def _has_return(plan: Plan, _registry: Registry, _limits: PlanLimits) -> list[PlanIssue]:
    if any(isinstance(step, Return) for step, _ in _walk(plan.steps)):
        return []
    return [PlanIssue(None, "plan has no return step")]
