"""Autopilot observe + draft (F18).

The drafter's input is built only from structured facts: tool and argument names
(from our own registry), label and evidence enums, counts, numbers, and link
*hosts* that passed a strict host-name check. Payload text, record text and
previews never reach it, so an attacker cannot write into our policy writer.
The model may only choose templates and parameters; anything off-template is
rejected (one retry), and a rule-based fallback always produces a draft.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from quarantix.ai.llm import LLMClient, LLMError
from quarantix.autopilot.templates import (
    MAX_CANDIDATES,
    Candidate,
    TemplateError,
    parse_candidate,
    template_catalog,
)
from quarantix.core.contracts import EVIDENCE, Event
from quarantix.core.registry import Registry

PROMPT_VERSION = "drafter_v1"
_HOST = re.compile(r"^[a-z0-9.-]{1,253}$")
_NAME = re.compile(r"^[a-z0-9_.-]{1,64}$")
_INTEGRITY = frozenset({"trusted", "untrusted"})
_CONFIDENTIALITY = frozenset({"public", "internal", "private", "secret"})
GOAL_KINDS = frozenset(
    {
        "money_to_attacker",
        "secret_exfiltrated",
        "link_planted",
        "data_to_public",
        "forbidden_action",
    }
)
DRAFT_SCHEMA: Mapping[str, Any] = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"template": {"type": "string"}, "parameters": {"type": "object"}},
                "required": ["template", "parameters"],
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["rules", "rationale"],
}
SYSTEM_PROMPT = (
    f"You are the policy drafter of an AI-agent firewall ({PROMPT_VERSION}). You receive "
    "structured facts about a breach: which tool call caused damage and the labels of its "
    "arguments. Propose the smallest set of rules (1-3) that would have stopped it without "
    "blocking legitimate work. Use only the listed templates and tools. Prefer narrow rules "
    "on the exact tool and argument. Reply with JSON: rules (template + parameters) and a "
    "rationale of at most two sentences."
)


@dataclass(frozen=True, slots=True)
class ArgFacts:
    integrity: str
    evidence: str
    confidentiality: str
    critical: bool
    link_hosts: tuple[str, ...] = ()

    def to_wire(self) -> dict[str, Any]:
        return {
            "integrity": self.integrity,
            "evidence": self.evidence,
            "confidentiality": self.confidentiality,
            "critical": self.critical,
            "link_hosts": list(self.link_hosts),
        }


@dataclass(frozen=True, slots=True)
class BreachFacts:
    """What Autopilot learns from a breach. No free text from the attacker, by construction."""

    domain: str
    agent: str
    goal_kind: str
    defender: str
    tool: str | None
    args: Mapping[str, ArgFacts] = field(default_factory=dict)
    allowed_hosts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (self.domain, self.agent, self.defender, *((self.tool and [self.tool]) or [])):
            if not _NAME.match(name):
                raise ValueError(f"not a plain name: {name[:20]!r}")
        if self.goal_kind not in GOAL_KINDS:
            raise ValueError(f"unknown goal kind {self.goal_kind!r}")
        for arg, facts in self.args.items():
            if not _NAME.match(arg):
                raise ValueError("argument names must be plain names")
            if facts.integrity not in _INTEGRITY or facts.evidence not in EVIDENCE:
                raise ValueError("labels must be enum values")
            if facts.confidentiality not in _CONFIDENTIALITY:
                raise ValueError("labels must be enum values")
            if not all(_HOST.match(h) for h in facts.link_hosts):
                raise ValueError("link hosts must be plain host names")
        if not all(_HOST.match(h) for h in self.allowed_hosts):
            raise ValueError("allowed hosts must be plain host names")

    def to_wire(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "agent": self.agent,
            "goal_kind": self.goal_kind,
            "defender": self.defender,
            "tool": self.tool,
            "args": {name: a.to_wire() for name, a in sorted(self.args.items())},
            "allowed_hosts": list(self.allowed_hosts),
        }


# ---------------------------------------------------------------- observe


class Observer:
    """Per agent and tool statistics from Gate events (enum values and counts only)."""

    def __init__(self) -> None:
        self.calls: Counter[tuple[str, str]] = Counter()
        self.evidence: Counter[tuple[str, str, str, str]] = Counter()  # agent, tool, arg, evidence
        self.decisions: Counter[tuple[str, str, str]] = Counter()  # agent, tool, rule (non-allow)
        self.breaches: Counter[tuple[str, str]] = Counter()  # domain, goal kind

    def consume(self, event: Event) -> None:
        if event.kind == "tool.call" and event.tool:
            self.calls[(event.agent, event.tool)] += 1
            for name, preview in (event.args or {}).items():
                evidence = str(preview.get("evidence", ""))
                if evidence in EVIDENCE:
                    self.evidence[(event.agent, event.tool, name, evidence)] += 1
            if event.decision is not None and event.decision.kind != "allow":
                self.decisions[(event.agent, event.tool, event.decision.rule)] += 1

    def stats_for(self, agent: str) -> dict[str, Any]:
        tools: dict[str, Any] = {}
        for (who, tool), count in self.calls.items():
            if who != agent:
                continue
            entry = tools.setdefault(tool, {"calls": 0, "args": {}, "non_allow": {}})
            entry["calls"] = count
        for (who, tool, arg, evidence), count in self.evidence.items():
            if who == agent and tool in tools:
                tools[tool]["args"].setdefault(arg, {})[evidence] = count
        for (who, tool, rule), count in self.decisions.items():
            if who == agent and tool in tools:
                tools[tool]["non_allow"][rule] = count
        return {"agent": agent, "tools": dict(sorted(tools.items()))}


# ---------------------------------------------------------------- draft


@dataclass(frozen=True, slots=True)
class Draft:
    candidates: tuple[Candidate, ...]
    rationale: str
    source: Literal["llm", "fallback"]
    notes: tuple[str, ...] = ()


def drafter_input(facts: BreachFacts, stats: Mapping[str, Any], registry: Registry) -> str:
    """The complete user message the model sees (structured data only)."""
    tools = [
        {
            "name": spec["name"],
            "kind": spec["kind"],
            "arguments": sorted(spec["arg_schema"].get("properties", {})),
        }
        for spec in registry.catalog()
    ]
    document = {
        "breach": facts.to_wire(),
        "statistics": stats,
        "tools": tools,
        "templates": template_catalog(),
    }
    return json.dumps(document, sort_keys=True)


class Drafter:
    def __init__(
        self,
        llm: LLMClient | None,
        model: str,
        *,
        max_tokens: int = 1024,
        budget_ok: Callable[[], bool] = lambda: True,
    ) -> None:
        self.llm = llm
        self.model = model
        self.max_tokens = max_tokens
        self.budget_ok = budget_ok

    async def draft(
        self, facts: BreachFacts, stats: Mapping[str, Any], registry: Registry
    ) -> Draft:
        if self.llm is None or not self.budget_ok():
            return fallback_draft(facts, registry, note="no model or budget: rule-based draft")
        user = drafter_input(facts, stats, registry)
        notes: list[str] = []
        for _attempt in range(2):  # one retry on off-template output
            try:
                reply = await self.llm.json(
                    model=self.model, system=SYSTEM_PROMPT, user=user,
                    schema=DRAFT_SCHEMA, max_tokens=self.max_tokens,
                )  # fmt: skip
            except LLMError as exc:
                return fallback_draft(facts, registry, note=f"model failed: {type(exc).__name__}")
            try:
                return _parse(reply.value, registry)
            except TemplateError as exc:
                notes.append(f"off-template output rejected: {exc}")
                user += f"\n\nYour previous reply was rejected: {exc}. Use only the templates."
        return fallback_draft(facts, registry, note="; ".join(notes))


def _parse(value: Any, registry: Registry) -> Draft:
    if not isinstance(value, Mapping) or not isinstance(value.get("rules"), Sequence):
        raise TemplateError("the reply must have a rules list")
    rules = list(value["rules"])
    if not 1 <= len(rules) <= MAX_CANDIDATES:
        raise TemplateError(f"propose 1 to {MAX_CANDIDATES} rules")
    candidates = tuple(parse_candidate(raw, registry) for raw in rules)
    rationale = str(value.get("rationale") or "")[:400]
    return Draft(candidates, rationale, "llm")


def fallback_draft(facts: BreachFacts, registry: Registry, *, note: str = "") -> Draft:
    """Deterministic mapping from breach facts to templates (the demo never depends on a model)."""
    notes = (note,) if note else ()
    tool = facts.tool
    if tool is None or tool not in registry:
        raise TemplateError("the breach has no known damaging tool call")
    spec = registry.get(tool)
    candidates: list[Candidate] = []
    rationale = ""
    for name, arg in sorted(facts.args.items()):
        if arg.integrity != "trusted" and arg.link_hosts:
            foreign = [h for h in arg.link_hosts if h not in facts.allowed_hosts]
            if foreign:
                candidates.append(
                    Candidate("no_foreign_links", {
                        "tool": tool, "arg": name, "allowed_hosts": sorted(facts.allowed_hosts),
                    })
                )  # fmt: skip
                rationale = (
                    f"Untrusted text carried a link to {foreign[0]} into {tool}.{name}. "
                    "Block links to unknown hosts in untrusted text; known hosts still pass."
                )
    if not candidates:
        untrusted = [n for n, a in sorted(facts.args.items()) if a.integrity != "trusted"]
        if spec.kind != "source" and untrusted:
            arg = untrusted[0]
            decision = "block" if facts.args[arg].evidence in ("exact", "traced") else "ask"
            candidates.append(
                Candidate("require_trusted", {"tool": tool, "arg": arg, "decision": decision})
            )
            rationale = (
                f"The {arg} of {tool} came from untrusted content. "
                f"Require it to come from a trusted source ({decision} otherwise)."
            )
        else:
            candidates.append(Candidate("block_untrusted_context", {"tool": tool}))
            rationale = (
                f"{tool} was triggered by untrusted content. "
                "Block it when the context is untrusted."
            )
    return Draft(tuple(candidates), rationale, "fallback", notes)
