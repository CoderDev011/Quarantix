"""Plan language (docs/contracts.md section 4): immutable step types and a structural parser.

`parse_plan` checks shape only (ops, keys, reference syntax, unique ids). Whether
tools exist and references are defined in scope is the validator's job (F09).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_VERSION = 1
_REF = re.compile(r"^\$([a-z_][a-z0-9_]*)((?:\.[a-z_][a-z0-9_]*|\[\d+\])*)$")
_REF_PART = re.compile(r"\.([a-z_][a-z0-9_]*)|\[(\d+)\]")
_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
TESTS = frozenset({"truthy", "eq", "ne", "lt", "le", "gt", "ge", "in"})

Literal_ = str | int | float | bool | None


class PlanError(ValueError):
    def __init__(self, message: str, step_id: str | None = None) -> None:
        self.step_id = step_id
        super().__init__(f"step {step_id}: {message}" if step_id else message)


@dataclass(frozen=True, slots=True)
class Ref:
    """A reference like `$name.field[0]`: a root variable and a path of fields and indexes."""

    root: str
    path: tuple[str | int, ...] = ()

    def __str__(self) -> str:
        parts = "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in self.path)
        return f"${self.root}{parts}"


Arg = Ref | Literal_


@dataclass(frozen=True, slots=True)
class Call:
    id: str
    tool: str
    args: Mapping[str, Arg]
    out: str | None = None


@dataclass(frozen=True, slots=True)
class Extract:
    id: str
    source: Ref
    fields: Mapping[str, str]
    out: str


@dataclass(frozen=True, slots=True)
class Cond:
    ref: Ref
    test: str
    value: Any = None


@dataclass(frozen=True, slots=True)
class If:
    id: str
    cond: Cond
    then: tuple[Step, ...]
    else_: tuple[Step, ...] = ()


@dataclass(frozen=True, slots=True)
class ForEach:
    id: str
    items: Ref
    as_: str
    body: tuple[Step, ...]
    collect: Ref | None = None
    out: str | None = None


@dataclass(frozen=True, slots=True)
class Format:
    id: str
    template: str
    values: Mapping[str, Ref]
    out: str


@dataclass(frozen=True, slots=True)
class Return:
    id: str
    value: Ref | str


Step = Call | Extract | If | ForEach | Format | Return


@dataclass(frozen=True, slots=True)
class Plan:
    steps: tuple[Step, ...]
    needs_approval: bool = False
    reason: str | None = None


def parse_ref(text: str) -> Ref:
    match = _REF.match(text)
    if match is None:
        raise ValueError(f"invalid reference {text!r}")
    path = tuple(
        field if field else int(index) for field, index in _REF_PART.findall(match.group(2))
    )
    return Ref(match.group(1), path)


def parse_plan(data: Mapping[str, Any]) -> Plan:
    if not isinstance(data, Mapping):
        raise PlanError("a plan must be a JSON object")
    _check_keys(data, {"schema_version", "steps", "needs_approval", "reason"}, None)
    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise PlanError(f"unsupported schema_version {data.get('schema_version')!r}")
    parser = _Parser()
    steps = parser.steps(data.get("steps", []), None)
    reason = data.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise PlanError("reason must be text")
    return Plan(steps, bool(data.get("needs_approval", False)), reason)


_STEP_KEYS: Mapping[str, frozenset[str]] = {
    "call": frozenset({"op", "id", "tool", "args", "out"}),
    "extract": frozenset({"op", "id", "source", "fields", "out"}),
    "if": frozenset({"op", "id", "cond", "then", "else"}),
    "for_each": frozenset({"op", "id", "items", "as", "body", "collect", "out"}),
    "format": frozenset({"op", "id", "template", "values", "out"}),
    "return": frozenset({"op", "id", "value"}),
}
_REQUIRED: Mapping[str, tuple[str, ...]] = {
    "call": ("tool",),
    "extract": ("source", "fields", "out"),
    "if": ("cond", "then"),
    "for_each": ("items", "as", "body"),
    "format": ("template", "values", "out"),
    "return": ("value",),
}


def _check_keys(
    data: Mapping[str, Any], allowed: frozenset[str] | set[str], step: str | None
) -> None:
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise PlanError(f"unknown keys {unknown}", step)


class _Parser:
    def __init__(self) -> None:
        self.seen: set[str] = set()

    def steps(self, raw: Any, parent: str | None) -> tuple[Step, ...]:
        if not isinstance(raw, list):
            raise PlanError("steps must be a list", parent)
        return tuple(self.step(item) for item in raw)

    def step(self, raw: Any) -> Step:
        if not isinstance(raw, Mapping):
            raise PlanError("each step must be a JSON object")
        sid = raw.get("id")
        if not isinstance(sid, str) or not sid.strip():
            raise PlanError("each step needs a non-empty id")
        if sid in self.seen:
            raise PlanError(f"duplicate step id {sid!r}", sid)
        self.seen.add(sid)
        op = raw.get("op")
        if not isinstance(op, str) or op not in _STEP_KEYS:
            raise PlanError(f"unknown op {op!r}", sid)
        _check_keys(raw, _STEP_KEYS[op], sid)
        for key in _REQUIRED[op]:
            if key not in raw:
                raise PlanError(f"missing required key {key!r}", sid)
        try:
            return self.build(op, sid, raw)
        except ValueError as exc:
            if isinstance(exc, PlanError):
                raise
            raise PlanError(str(exc), sid) from None

    def build(self, op: str, sid: str, raw: Mapping[str, Any]) -> Step:
        if op == "call":
            args = raw.get("args", {})
            if not isinstance(args, Mapping):
                raise ValueError("args must be an object")
            return Call(
                sid, _text(raw["tool"], "tool"), {k: _arg(v) for k, v in args.items()}, _out(raw)
            )
        if op == "extract":
            fields = raw["fields"]
            if not isinstance(fields, Mapping) or not all(
                isinstance(v, str) for v in fields.values()
            ):
                raise ValueError("fields must map names to field types")
            return Extract(sid, _ref(raw["source"]), dict(fields), _name(raw["out"], "out"))
        if op == "if":
            cond = raw["cond"]
            if not isinstance(cond, Mapping):
                raise ValueError("cond must be an object")
            _check_keys(cond, {"ref", "test", "value"}, sid)
            test = cond.get("test", "truthy")
            if test not in TESTS:
                raise ValueError(f"invalid test {test!r}; use {sorted(TESTS)}")
            return If(
                sid,
                Cond(_ref(cond.get("ref")), test, cond.get("value")),
                self.steps(raw["then"], sid),
                self.steps(raw.get("else", []), sid),
            )
        if op == "for_each":
            collect = raw.get("collect")
            return ForEach(
                sid,
                _ref(raw["items"]),
                _name(raw["as"], "as"),
                self.steps(raw["body"], sid),
                None if collect is None else _ref(collect),
                _out(raw),
            )
        if op == "format":
            values = raw["values"]
            if not isinstance(values, Mapping):
                raise ValueError("values must be an object")
            return Format(
                sid,
                _text(raw["template"], "template"),
                {k: _ref(v) for k, v in values.items()},
                _name(raw["out"], "out"),
            )
        value = raw["value"]
        return Return(
            sid,
            _ref(value)
            if isinstance(value, str) and value.startswith("$")
            else _text(value, "value"),
        )


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{what} must be text")
    return value


def _name(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _NAME.match(value):
        raise ValueError(f"{what} must be a lowercase name, got {value!r}")
    return value


def _out(raw: Mapping[str, Any]) -> str | None:
    return None if raw.get("out") is None else _name(raw["out"], "out")


def _ref(value: Any) -> Ref:
    if not isinstance(value, str):
        raise ValueError(f"invalid reference {value!r}")
    return parse_ref(value)


def _arg(value: Any) -> Arg:
    if isinstance(value, str) and value.startswith("$"):
        return parse_ref(value)
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise ValueError(f"literal arguments must be single values, got {type(value).__name__}")
