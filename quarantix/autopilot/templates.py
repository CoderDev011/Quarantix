"""Autopilot rule templates (F18). The model picks templates and parameters; code writes YAML.

Every candidate is validated against the template list and the agent's tool
registry before anything is built. The pack is serialized with `yaml.safe_dump`,
so no parameter can inject YAML. Allow-type templates always need a human.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import yaml

from quarantix.core.registry import Registry
from quarantix.engine.policy import compile_pack

_HOST = re.compile(
    r"^(?=.{1,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
_SAFE = re.compile(r"[^a-z0-9-]+")
MAX_VALUES = 20
MAX_CANDIDATES = 5

# name -> (required parameters, tighten-only?, one-line description for the drafter)
TEMPLATES: Mapping[str, tuple[tuple[str, ...], bool, str]] = {
    "require_trusted": (
        ("tool", "arg", "decision"), True,
        "Ask or block unless the argument is trusted (decision: ask or block).",
    ),
    "cap_number": (("tool", "arg", "max"), True, "Ask when a numeric argument is above max."),
    "allow_list": (("tool", "arg", "values"), True, "Block values outside a list (at most 20)."),
    "block_untrusted_context": (("tool",), True, "Block the tool when the context is untrusted."),
    "no_foreign_links": (
        ("tool", "arg", "allowed_hosts"), True,
        "Block when the argument is not trusted and links outside the allowed hosts.",
    ),
    "require_approval": (("tool",), True, "Ask a person before every call of the tool."),
    "allow_pattern": (
        ("tool", "arg", "values"), False,
        "Allow the tool when the argument is trusted and one of the values (needs a human).",
    ),
}  # fmt: skip


class TemplateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Candidate:
    template: str
    params: Mapping[str, Any]

    @property
    def tighten_only(self) -> bool:
        return TEMPLATES[self.template][1]

    def to_wire(self) -> dict[str, Any]:
        return {"template": self.template, "parameters": dict(self.params)}


def template_catalog() -> list[dict[str, Any]]:
    """What the drafter may choose from."""
    return [
        {"template": name, "parameters": list(params), "effect": text}
        for name, (params, _, text) in TEMPLATES.items()
    ]


def parse_candidate(raw: Any, registry: Registry) -> Candidate:
    """Validate one model-proposed candidate. Anything off-template raises TemplateError."""
    if not isinstance(raw, Mapping):
        raise TemplateError("a candidate must be an object")
    name = str(raw.get("template", ""))
    if name not in TEMPLATES:
        raise TemplateError(f"unknown template {name!r}")
    params_raw = raw.get("parameters", raw.get("params"))
    if not isinstance(params_raw, Mapping):
        raise TemplateError(f"{name}: parameters must be an object")
    required = TEMPLATES[name][0]
    unknown = sorted(set(params_raw) - set(required))
    missing = [p for p in required if p not in params_raw]
    if unknown or missing:
        raise TemplateError(f"{name}: unknown {unknown} / missing {missing} parameters")

    tool = params_raw["tool"]
    if not isinstance(tool, str) or tool not in registry:
        raise TemplateError(f"{name}: unknown tool {tool!r}")
    spec = registry.get(tool)
    params: dict[str, Any] = {"tool": tool}
    if "arg" in required:
        arg = params_raw["arg"]
        if not isinstance(arg, str) or arg not in spec.arg_schema.get("properties", {}):
            raise TemplateError(f"{name}: tool {tool} has no argument {arg!r}")
        params["arg"] = arg
    if "decision" in required:
        decision = params_raw["decision"]
        if decision not in ("ask", "block"):
            raise TemplateError(f"{name}: decision must be ask or block")
        params["decision"] = decision
    if "max" in required:
        value = params_raw["max"]
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise TemplateError(f"{name}: max must be a non-negative number")
        params["max"] = float(value)
    if "values" in required:
        values = params_raw["values"]
        if (
            not isinstance(values, Sequence) or isinstance(values, str)
            or not 1 <= len(values) <= MAX_VALUES
            or not all(isinstance(v, str | int | float) and not isinstance(v, bool) for v in values)
            or any(isinstance(v, str) and len(v) > 64 for v in values)
        ):  # fmt: skip
            raise TemplateError(f"{name}: values must be 1-{MAX_VALUES} short scalars")
        params["values"] = sorted({v for v in values}, key=str)
    if "allowed_hosts" in required:
        hosts = params_raw["allowed_hosts"]
        if not isinstance(hosts, Sequence) or isinstance(hosts, str) or len(hosts) > MAX_VALUES:
            raise TemplateError(f"{name}: allowed_hosts must be a list")
        clean = sorted({str(h).strip().lower().rstrip(".") for h in hosts})
        if not all(_HOST.match(h) for h in clean):
            raise TemplateError(f"{name}: allowed_hosts must be plain host names")
        params["allowed_hosts"] = clean
    return Candidate(name, params)


def _rule(candidate: Candidate) -> dict[str, Any]:
    p = candidate.params
    tool = p["tool"]
    name = _SAFE.sub("-", f"{candidate.template}-{tool}-{p.get('arg', '')}".lower()).strip("-")
    rule: dict[str, Any] = {"name": name[:60], "tool": tool, "origin": "autopilot"}
    match candidate.template:
        case "require_trusted":
            rule["when"] = [{"arg": p["arg"], "integrity": "not_trusted"}]
            rule["decision"] = p["decision"]
            rule["reason"] = f"The {p['arg']} of {tool} must come from a trusted source."
        case "cap_number":
            rule["when"] = [{"arg": p["arg"], "value": {"gt": p["max"]}}]
            rule["decision"] = "ask"
            rule["reason"] = f"{tool} with {p['arg']} above {p['max']:g} needs a person."
        case "allow_list":
            rule["when"] = [{"arg": p["arg"], "value": {"not_in": list(p["values"])}}]
            rule["decision"] = "block"
            rule["reason"] = f"{tool} only accepts known values for {p['arg']}."
        case "block_untrusted_context":
            rule["when"] = [{"context": {"integrity": "untrusted"}}]
            rule["decision"] = "block"
            rule["reason"] = f"Untrusted content must not trigger {tool}."
        case "no_foreign_links":
            rule["when"] = [
                {"arg": p["arg"], "integrity": "not_trusted",
                 "value": {"has_link_outside_allowed_hosts": True}},
            ]  # fmt: skip
            rule["decision"] = "block"
            rule["reason"] = (
                f"The {p['arg']} of {tool} copies a link to an unknown host from untrusted text."
            )
        case "require_approval":
            rule["decision"] = "ask"
            rule["reason"] = f"Every {tool} call needs a person."
        case "allow_pattern":
            rule["when"] = [
                {"arg": p["arg"], "integrity": "trusted", "value": {"in": list(p["values"])}}
            ]
            rule["decision"] = "allow"
            rule["reason"] = f"Known-safe {tool} calls (approved by a person)."
    return rule


def pack_name(proposal_id: str) -> str:
    return f"autopilot-{_SAFE.sub('-', proposal_id.lower())[:40]}"


def build_pack(proposal_id: str, agent: str, candidates: Sequence[Candidate]) -> str:
    """The YAML of the candidate pack. It is compiled here, so a bad build fails early."""
    if not candidates:
        raise TemplateError("no candidate rules")
    hosts = sorted({h for c in candidates for h in c.params.get("allowed_hosts", ())})
    seen: set[str] = set()
    rules = []
    for candidate in candidates[:MAX_CANDIDATES]:
        rule = _rule(candidate)
        if rule["name"] in seen:
            continue
        seen.add(rule["name"])
        rules.append(rule)
    document: dict[str, Any] = {
        "schema_version": 1,
        "pack": pack_name(proposal_id),
        "applies_to": [agent],
        "origin": "autopilot",
        "rules": rules,
    }
    if hosts:
        document["allowed_link_hosts"] = hosts
    text = yaml.safe_dump(document, sort_keys=False, allow_unicode=False)
    compile_pack(text)  # raises PolicyError if a template ever produced something invalid
    return text
