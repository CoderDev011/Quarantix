"""Tool registry (F02, contracts sections 3 and 10.4).

Each tool declares, once, its kind, risk, audience, labels and critical arguments,
so every way in (full mode, SDK, MCP gateway, arena) judges it the same way.
Looking up an unknown name returns the default-deny spec: a high-risk sink with
an external audience whose arguments are all critical.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import typing
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Literal
from urllib.parse import urlsplit

import pydantic

from agentwall.core.labels import Confidentiality, Integrity, Label

Kind = Literal["source", "sink", "both"]
Risk = Literal["low", "medium", "high"]
Audience = Literal["self", "internal", "external", "public"]
RecordLookup = Callable[[str, str], Mapping[str, Any] | None]

KINDS: frozenset[str] = frozenset(typing.get_args(Kind))
RISKS: frozenset[str] = frozenset(typing.get_args(Risk))
AUDIENCES: frozenset[str] = frozenset(typing.get_args(Audience))
ALL_ARGS = "*"
DEFAULT_OUTPUT_LABEL = Label(Integrity.UNTRUSTED, Confidentiality.INTERNAL, frozenset())


# ---------------------------------------------------------------- audience rules


@dataclass(frozen=True, slots=True)
class ChannelAllowlist:
    """Internal if the channel argument is a known channel, otherwise external."""

    param: str
    known: frozenset[str]

    def resolve(self, args: Mapping[str, Any], lookup: RecordLookup | None) -> Audience:
        return "internal" if args.get(self.param) in self.known else "external"

    def to_wire(self) -> dict[str, Any]:
        return {"rule": "channel_allowlist", "param": self.param, "known": sorted(self.known)}


@dataclass(frozen=True, slots=True)
class DestinationDomain:
    """Internal if the destination (email or URL) is on an organization domain."""

    param: str
    org_domains: frozenset[str]

    def resolve(self, args: Mapping[str, Any], lookup: RecordLookup | None) -> Audience:
        value = args.get(self.param)
        if not isinstance(value, str):
            return "external"
        host = _destination_host(value)
        on_org_domain = any(host == d or host.endswith("." + d) for d in self.org_domains)
        return "internal" if on_org_domain else "external"

    def to_wire(self) -> dict[str, Any]:
        return {"rule": "destination_domain", "param": self.param, "org": sorted(self.org_domains)}


@dataclass(frozen=True, slots=True)
class RecordField:
    """Look up a record and map one of its fields to an audience."""

    store: str
    id_param: str
    field: str
    mapping: Mapping[str, Audience]

    def resolve(self, args: Mapping[str, Any], lookup: RecordLookup | None) -> Audience:
        record_id = args.get(self.id_param)
        if lookup is None or not isinstance(record_id, str):
            return "external"
        record = lookup(self.store, record_id)
        value = None if record is None else record.get(self.field)
        if not isinstance(value, str):
            return "external"
        return self.mapping.get(value, "external")

    def to_wire(self) -> dict[str, Any]:
        return {
            "rule": "record_field",
            "store": self.store,
            "id_param": self.id_param,
            "field": self.field,
            "mapping": dict(sorted(self.mapping.items())),
        }


AudienceRule = ChannelAllowlist | DestinationDomain | RecordField


def _destination_host(value: str) -> str:
    if "://" not in value and "@" in value:
        host = value.rsplit("@", 1)[1]
    else:
        host = urlsplit(value).hostname or value
    return host.strip().rstrip(".").lower()


def resolve_audience(
    spec: ToolSpec, args: Mapping[str, Any], lookup: RecordLookup | None = None
) -> Audience:
    """The audience of a call. Any failure to compute it means external (default deny)."""
    if isinstance(spec.audience, str):
        return spec.audience
    try:
        audience = spec.audience.resolve(args, lookup)
    except Exception:  # a broken rule or lookup must never widen the audience
        return "external"
    return audience if audience in AUDIENCES else "external"


# ---------------------------------------------------------------- tool spec


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    kind: Kind
    description: str
    arg_schema: Mapping[str, Any]
    fn: Callable[..., Any] | None = None
    output_label: Label = DEFAULT_OUTPUT_LABEL
    field_labels: Mapping[str, Label] = field(default_factory=dict)
    endorses_output: bool = False
    audience: Audience | AudienceRule = "external"
    risk: Risk = "high"
    critical_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("tool name is required")
        if self.kind not in KINDS:
            raise ValueError(f"tool {self.name!r}: invalid kind {self.kind!r}")
        if self.risk not in RISKS:
            raise ValueError(f"tool {self.name!r}: invalid risk {self.risk!r}")
        if isinstance(self.audience, str) and self.audience not in AUDIENCES:
            raise ValueError(f"tool {self.name!r}: invalid audience {self.audience!r}")
        if not self.description.strip():
            raise ValueError(f"tool {self.name!r}: a description is required")
        if ALL_ARGS not in self.critical_args:
            known = set(self.arg_schema.get("properties", {}))
            unknown = [arg for arg in self.critical_args if arg not in known]
            if unknown:
                raise ValueError(f"tool {self.name!r}: critical args not in schema: {unknown}")

    def is_critical(self, arg: str) -> bool:
        return ALL_ARGS in self.critical_args or arg in self.critical_args

    def catalog_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "kind": self.kind,
            "arg_schema": self.arg_schema,
        }

    def metadata_wire(self) -> dict[str, Any]:
        """Everything that affects decisions, in canonical form (feeds the registry version)."""
        audience = self.audience if isinstance(self.audience, str) else self.audience.to_wire()
        return {
            **self.catalog_entry(),
            "output_label": self.output_label.to_wire(),
            "field_labels": {k: v.to_wire() for k, v in sorted(self.field_labels.items())},
            "endorses_output": self.endorses_output,
            "audience": audience,
            "risk": self.risk,
            "critical_args": sorted(self.critical_args),
        }


@lru_cache(maxsize=1024)
def default_deny_spec(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        kind="sink",
        description="Unregistered tool (default deny).",
        arg_schema={},
        audience="external",
        risk="high",
        critical_args=(ALL_ARGS,),
    )


# ---------------------------------------------------------------- schemas from Python functions


def schema_from_signature(fn: Callable[..., Any]) -> dict[str, Any]:
    """JSON schema of a function's parameters, built from its type hints.

    Titles are stripped: they add tokens to every prompt and carry no meaning.
    """
    hints = typing.get_type_hints(fn)
    fields: dict[str, Any] = {}
    for param in inspect.signature(fn).parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise ValueError(f"tool {fn.__name__!r}: *args and **kwargs are not allowed")
        default = ... if param.default is param.empty else param.default
        fields[param.name] = (hints.get(param.name, Any), default)
    model = pydantic.create_model(f"{fn.__name__}_args", **fields)
    return _strip_titles(model.model_json_schema())


def _strip_titles(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_titles(v) for k, v in node.items() if k != "title"}
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


# ---------------------------------------------------------------- registry


class Registry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}
        self._catalog: list[dict[str, Any]] | None = None
        self._version: str | None = None

    def register(self, spec: ToolSpec) -> None:
        existing = self._specs.get(spec.name)
        if existing is not None:
            if existing == spec:
                return  # idempotent
            raise ValueError(f"tool {spec.name!r} is already registered with a different spec")
        self._specs[spec.name] = spec
        self._catalog = None
        self._version = None

    def tool(
        self,
        *,
        kind: Kind,
        name: str | None = None,
        description: str | None = None,
        output_label: Label = DEFAULT_OUTPUT_LABEL,
        field_labels: Mapping[str, Label] | None = None,
        endorses_output: bool = False,
        audience: Audience | AudienceRule = "external",
        risk: Risk = "high",
        critical_args: tuple[str, ...] = (),
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Register a Python function as a tool. Returns the function unchanged."""

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register(
                ToolSpec(
                    name=name or fn.__name__,
                    kind=kind,
                    description=description or inspect.getdoc(fn) or "",
                    arg_schema=schema_from_signature(fn),
                    fn=fn,
                    output_label=output_label,
                    field_labels=dict(field_labels or {}),
                    endorses_output=endorses_output,
                    audience=audience,
                    risk=risk,
                    critical_args=critical_args,
                )
            )
            return fn

        return decorate

    def get(self, name: str) -> ToolSpec:
        return self._specs.get(name) or default_deny_spec(name)

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def names(self) -> list[str]:
        return sorted(self._specs)

    def catalog(self) -> list[dict[str, Any]]:
        """Name, description, kind and argument schema of every tool, sorted by name."""
        if self._catalog is None:
            self._catalog = [self._specs[n].catalog_entry() for n in sorted(self._specs)]
        return list(self._catalog)

    @property
    def version(self) -> str:
        if self._version is None:
            canonical = json.dumps(
                [self._specs[n].metadata_wire() for n in sorted(self._specs)],
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            self._version = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        return self._version
