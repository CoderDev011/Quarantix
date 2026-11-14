"""Policy engine (F04): a labeled tool call -> allow, ask or block, deterministically.

Core rules C1-C3 judge sink calls from labels alone; C4 cleans final answers.
Policy packs (YAML, contracts section 9) are compiled once into closures and
indexed by tool name, so evaluation never parses anything. The combine order is
fixed: a core block always wins, a pack block beats everything else, and a core
ask is relaxed only by an allow rule that names the exact tool.
"""

from __future__ import annotations

import hashlib
import operator
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.parse import urlsplit

import yaml
from yaml.constructor import SafeConstructor
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from quarantix.core.contracts import (
    DECISION_KINDS,
    EVIDENCE,
    SEVERITY,
    ArgValue,
    Decision,
    DecisionKind,
    ToolCallRequest,
)
from quarantix.core.labels import Confidentiality, Integrity, Label, join_all
from quarantix.core.registry import AUDIENCES, Audience, RecordLookup, ToolSpec, resolve_audience

C1 = "core/C1-untrusted-critical-arg"
C2 = "core/C2-confidentiality-exceeds-audience"
C3 = "core/C3-untrusted-context-high-risk"
C4 = "core/C4-link-leak"
DEFAULT_RULE = "default"

AgentMode = Literal["enforce", "monitor", "off"]
AGENT_MODES = frozenset({"enforce", "monitor", "off"})

CLEARANCE: Mapping[str, Confidentiality] = {
    "public": Confidentiality.PUBLIC,
    "external": Confidentiality.PUBLIC,
    "internal": Confidentiality.PRIVATE,
    "self": Confidentiality.SECRET,
}

LINK_REPLACEMENT = "[link removed: untrusted destination]"


class PolicyError(ValueError):
    """A policy pack could not be compiled. Carries the 1-based line and column."""

    def __init__(self, message: str, line: int | None = None, column: int | None = None) -> None:
        self.line = line
        self.column = column
        self.message = message
        where = f"line {line}, column {column}: " if line is not None else ""
        super().__init__(where + message)


# ---------------------------------------------------------------- links (C4 and the link operator)

_URL = re.compile(r"https?://[^\s<>\"'()\[\]]+", re.IGNORECASE)
_MARKDOWN_LINK = re.compile(r"!?\[[^\]\n]*\]\(\s*(https?://[^\s)]+)[^)]*\)", re.IGNORECASE)
_TRAILING_PUNCTUATION = ".,;:!?"


def _normalize_host(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _host_allowed(url: str, allowed: frozenset[str]) -> bool:
    host = _normalize_host(urlsplit(url).hostname or "")
    return bool(host) and any(host == h or host.endswith("." + h) for h in allowed)


def _has_foreign_link(value: Any, allowed: frozenset[str]) -> bool:
    if not isinstance(value, str):
        return False
    return any(
        not _host_allowed(match.group(0).rstrip(_TRAILING_PUNCTUATION), allowed)
        for match in _URL.finditer(value)
    )


def check_answer(text: str, label: Label, allowed_hosts: Iterable[str]) -> tuple[str, list[str]]:
    """Rule C4: strip links to non-allowed hosts from an answer that carries internal data.

    Returns the cleaned text and the removed URLs. Public answers are left alone.
    """
    if label.confidentiality < Confidentiality.INTERNAL:
        return text, []
    allowed = frozenset(_normalize_host(h) for h in allowed_hosts)
    removed: list[str] = []

    def strip_markdown(match: re.Match[str]) -> str:
        url = match.group(1).rstrip(_TRAILING_PUNCTUATION)
        if _host_allowed(url, allowed):
            return match.group(0)
        removed.append(url)
        return LINK_REPLACEMENT

    def strip_bare(match: re.Match[str]) -> str:
        raw = match.group(0)
        url = raw.rstrip(_TRAILING_PUNCTUATION)
        if _host_allowed(url, allowed):
            return raw
        removed.append(url)
        return LINK_REPLACEMENT + raw[len(url) :]

    text = _MARKDOWN_LINK.sub(strip_markdown, text)
    return _URL.sub(strip_bare, text), removed


# ---------------------------------------------------------------- compiled packs


@dataclass(frozen=True, slots=True)
class _Context:
    """What pack conditions may look at."""

    request: ToolCallRequest
    audience: Audience
    hosts: frozenset[str]


Predicate = Callable[[_Context], bool]


@dataclass(frozen=True, slots=True)
class CompiledRule:
    name: str
    pack: str
    tool: str
    decision: DecisionKind
    reason: str
    origin: str
    arg: str | None
    predicates: tuple[Predicate, ...]

    @property
    def rule_id(self) -> str:
        return f"{self.pack}/{self.name}"

    def matches(self, context: _Context) -> bool:
        # Plain loops on purpose: this is the hot path, and all(<generator>) measured
        # ~3.5x slower here (p99 405 -> 168 us for 100 rules).
        for predicate in self.predicates:  # noqa: SIM110
            if not predicate(context):
                return False
        return True


@dataclass(frozen=True, slots=True)
class Pack:
    name: str
    applies_to: tuple[str, ...]
    modes: Mapping[str, AgentMode]
    allowed_link_hosts: frozenset[str]
    origin: str
    rules: tuple[CompiledRule, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    """One agent's view of a bundle: its rules indexed by tool, mode and link hosts."""

    agent: str
    mode: AgentMode
    allowed_link_hosts: frozenset[str]
    rules_by_tool: Mapping[str, tuple[CompiledRule, ...]]
    wildcard_rules: tuple[CompiledRule, ...]
    version: str

    def rules_for(self, tool: str) -> tuple[CompiledRule, ...]:
        return self.rules_by_tool.get(tool, ()) + self.wildcard_rules


class PolicyBundle:
    """All enabled packs. The version is a content hash (also the HTTP ETag)."""

    __slots__ = ("_views", "packs", "version")

    def __init__(self, packs: Iterable[Pack] = ()) -> None:
        self.packs = tuple(sorted(packs, key=lambda pack: pack.name))
        names = [pack.name for pack in self.packs]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate pack names in bundle: {names}")
        canonical = "\n".join(f"{pack.name}:{pack.digest}" for pack in self.packs)
        self.version = hashlib.sha256(canonical.encode()).hexdigest()[:12]
        self._views: dict[str, AgentPolicy] = {}

    def for_agent(self, agent: str) -> AgentPolicy:
        view = self._views.get(agent)
        if view is None:
            view = self._build_view(agent)
            self._views[agent] = view
        return view

    def _build_view(self, agent: str) -> AgentPolicy:
        applicable = [p for p in self.packs if "*" in p.applies_to or agent in p.applies_to]
        by_tool: dict[str, list[CompiledRule]] = {}
        wildcard: list[CompiledRule] = []
        for pack in applicable:
            for rule in pack.rules:
                if rule.tool == "*":
                    wildcard.append(rule)
                else:
                    by_tool.setdefault(rule.tool, []).append(rule)
        mode: AgentMode = "enforce"
        for pack in applicable:  # the first pack (by name) that sets this agent's mode wins
            if agent in pack.modes:
                mode = pack.modes[agent]
                break
        hosts = frozenset(h for p in applicable for h in p.allowed_link_hosts)
        return AgentPolicy(
            agent=agent,
            mode=mode,
            allowed_link_hosts=hosts,
            rules_by_tool={tool: tuple(rules) for tool, rules in by_tool.items()},
            wildcard_rules=tuple(wildcard),
            version=self.version,
        )


# ---------------------------------------------------------------- the pack compiler

_TOP_KEYS = frozenset(
    {"schema_version", "pack", "applies_to", "modes", "allowed_link_hosts", "origin", "rules"}
)
_RULE_KEYS = frozenset({"name", "tool", "when", "decision", "reason", "origin"})
_CONDITION_KEYS = frozenset(
    {"arg", "integrity", "confidentiality", "evidence", "value", "context", "audience"}
)
_ARG_CONDITIONS = frozenset({"integrity", "confidentiality", "evidence", "value"})
_INTEGRITY_VALUES = frozenset({"trusted", "untrusted", "not_trusted"})
_ORIGINS = frozenset({"human", "autopilot", "day-one"})
_COMPARISONS: Mapping[str, Callable[[Any, Any], Any]] = {
    "eq": operator.eq,
    "ne": operator.ne,
    "lt": operator.lt,
    "lte": operator.le,
    "gt": operator.gt,
    "gte": operator.ge,
}
_VALUE_OPERATORS = frozenset(
    {*_COMPARISONS, "in", "not_in", "regex", "startswith", "has_link_outside_allowed_hosts"}
)
_LOADER: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def compile_pack(text: str) -> Pack:
    """Compile one policy pack. Any problem raises PolicyError with its line number."""
    try:
        root = yaml.compose(text, Loader=_LOADER)
        if root is None:
            raise PolicyError("empty policy pack")
        # The version digest covers the exact source text: identical text gives the
        # same version and any edit (even formatting) gives a new one.
        return _Compiler(root, hashlib.sha256(text.encode()).hexdigest()).pack()
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        problem = getattr(exc, "problem", None) or str(exc)
        if mark is None:
            raise PolicyError(f"invalid YAML: {problem}") from exc
        raise PolicyError(f"invalid YAML: {problem}", mark.line + 1, mark.column + 1) from exc
    except RecursionError as exc:
        raise PolicyError("policy pack is nested too deeply") from exc


class _Compiler:
    def __init__(self, root: Node, digest: str) -> None:
        self.root = root
        self.digest = digest
        self.constructor = SafeConstructor()

    # -- helpers

    @staticmethod
    def error(node: Node, message: str) -> PolicyError:
        return PolicyError(message, node.start_mark.line + 1, node.start_mark.column + 1)

    def load(self, node: Node) -> Any:
        return self.constructor.construct_object(node, deep=True)

    def mapping(self, node: Node, what: str, allowed: frozenset[str]) -> dict[str, Node]:
        if not isinstance(node, MappingNode):
            raise self.error(node, f"{what} must be a mapping")
        result: dict[str, Node] = {}
        for key_node, value_node in node.value:
            key = self.load(key_node)
            if not isinstance(key, str):
                raise self.error(key_node, f"{what} keys must be text, got {key!r}")
            if key in result:
                raise self.error(key_node, f"duplicate key {key!r} in {what}")
            if key not in allowed:
                raise self.error(
                    key_node, f"unknown key {key!r} in {what}; allowed: {sorted(allowed)}"
                )
            result[key] = value_node
        return result

    def sequence(self, node: Node, what: str) -> list[Node]:
        if not isinstance(node, SequenceNode):
            raise self.error(node, f"{what} must be a list")
        return list(node.value)

    def text(self, node: Node, what: str) -> str:
        value = self.load(node)
        if not isinstance(value, str) or not value.strip():
            raise self.error(node, f"{what} must be non-empty text, got {value!r}")
        return value

    def word(self, node: Node, what: str) -> str:
        """A scalar exactly as written, so `off`, `no` and `yes` stay words, not booleans."""
        if not isinstance(node, ScalarNode) or not str(node.value).strip():
            raise self.error(node, f"{what} must be a single word")
        return str(node.value).strip()

    def text_list(self, node: Node, what: str) -> tuple[str, ...]:
        return tuple(self.text(item, f"each {what} entry") for item in self.sequence(node, what))

    def scalar_operand(self, node: Node, op: str) -> Any:
        value = self.load(node)
        if isinstance(value, dict | list):
            raise self.error(
                node, f"operator {op!r} needs a single value, not {type(value).__name__}"
            )
        return value

    # -- document

    def pack(self) -> Pack:
        top = self.mapping(self.root, "policy pack", _TOP_KEYS)
        version_node = top.get("schema_version")
        version = None if version_node is None else self.load(version_node)
        if version != 1 or isinstance(version, bool):
            raise self.error(
                version_node or self.root, f"schema_version must be 1, got {version!r}"
            )
        if "pack" not in top:
            raise self.error(self.root, "missing required key 'pack' (the pack name)")
        name = self.text(top["pack"], "pack")

        applies_to = ("*",)
        if "applies_to" in top:
            applies_to = self.text_list(top["applies_to"], "applies_to")

        modes: dict[str, AgentMode] = {}
        if "modes" in top:
            mode_nodes = top["modes"]
            if not isinstance(mode_nodes, MappingNode):
                raise self.error(mode_nodes, "modes must be a mapping of agent to mode")
            for key_node, value_node in mode_nodes.value:
                # Raw words, not YAML-1.1 values: an unquoted `off` would load as False.
                agent = self.word(key_node, "modes agent name")
                mode = self.word(value_node, "mode")
                if mode not in AGENT_MODES:
                    raise self.error(
                        value_node, f"invalid mode {mode!r}; use {sorted(AGENT_MODES)}"
                    )
                modes[agent] = cast(AgentMode, mode)  # validated just above

        hosts = frozenset()
        if "allowed_link_hosts" in top:
            hosts = frozenset(
                _normalize_host(h) for h in self.text_list(top["allowed_link_hosts"], "host")
            )

        origin = self.origin(top.get("origin"), "human")
        rules = self.rules(top.get("rules"), name, origin)
        return Pack(
            name=name,
            applies_to=applies_to,
            modes=modes,
            allowed_link_hosts=hosts,
            origin=origin,
            rules=rules,
            digest=self.digest,
        )

    def origin(self, node: Node | None, default: str) -> str:
        if node is None:
            return default
        origin = self.text(node, "origin")
        if origin not in _ORIGINS and not origin.startswith("autopilot:"):
            raise self.error(
                node, f"invalid origin {origin!r}; use human, day-one or autopilot:<id>"
            )
        return origin

    def rules(self, node: Node | None, pack: str, pack_origin: str) -> tuple[CompiledRule, ...]:
        if node is None:
            return ()
        compiled: list[CompiledRule] = []
        seen: set[str] = set()
        for rule_node in self.sequence(node, "rules"):
            fields = self.mapping(rule_node, "rule", _RULE_KEYS)
            for required in ("name", "tool", "decision"):
                if required not in fields:
                    raise self.error(rule_node, f"rule is missing required key {required!r}")
            name = self.text(fields["name"], "rule name")
            if name in seen:
                raise self.error(fields["name"], f"duplicate rule name {name!r}")
            seen.add(name)
            tool = self.text(fields["tool"], "tool")
            decision = self.load(fields["decision"])
            if decision not in DECISION_KINDS:
                raise self.error(fields["decision"], f"invalid decision {decision!r}")
            if tool == "*" and decision == "allow":
                raise self.error(
                    fields["tool"], "a wildcard tool ('*') can only ask or block, not allow"
                )
            reason = f"Policy rule {pack}/{name}"
            if "reason" in fields:
                reason = self.text(fields["reason"], "reason")
            conditions = []
            if "when" in fields:
                conditions = self.sequence(fields["when"], "when")
            predicates, first_arg = [], None
            for condition in conditions:
                predicate, arg = self.condition(condition)
                predicates.append(predicate)
                first_arg = first_arg or arg
            compiled.append(
                CompiledRule(
                    name=name,
                    pack=pack,
                    tool=tool,
                    decision=decision,
                    reason=reason,
                    origin=self.origin(fields.get("origin"), pack_origin),
                    arg=first_arg,
                    predicates=tuple(predicates),
                )
            )
        return tuple(compiled)

    def condition(self, node: Node) -> tuple[Predicate, str | None]:
        fields = self.mapping(node, "condition", _CONDITION_KEYS)
        arg_name = self.text(fields["arg"], "arg") if "arg" in fields else None
        needs_arg = sorted(_ARG_CONDITIONS & fields.keys())
        if needs_arg and arg_name is None:
            raise self.error(node, f"conditions on {needs_arg} need an 'arg'")

        arg_checks: list[Callable[[ArgValue, _Context], bool]] = []
        if "integrity" in fields:
            arg_checks.append(self.integrity_check(fields["integrity"]))
        if "confidentiality" in fields:
            arg_checks.append(self.confidentiality_check(fields["confidentiality"]))
        if "evidence" in fields:
            allowed = frozenset(self.text_list(fields["evidence"], "evidence"))
            bad = sorted(allowed - EVIDENCE)
            if bad:
                raise self.error(fields["evidence"], f"invalid evidence {bad}")
            arg_checks.append(lambda arg, _ctx: arg.evidence in allowed)
        if "value" in fields:
            arg_checks.extend(self.value_checks(fields["value"]))

        context_checks: list[Predicate] = []
        if "context" in fields:
            context_fields = self.mapping(fields["context"], "context", frozenset({"integrity"}))
            if "integrity" in context_fields:
                want_untrusted = self.integrity_value(context_fields["integrity"]) != "trusted"
                context_checks.append(
                    lambda ctx: (
                        (ctx.request.context.integrity is Integrity.UNTRUSTED) == want_untrusted
                    )
                )
        if "audience" in fields:
            audience = self.load(fields["audience"])
            if audience not in AUDIENCES:
                raise self.error(fields["audience"], f"invalid audience {audience!r}")
            context_checks.append(lambda ctx: ctx.audience == audience)

        arg_check_list = tuple(arg_checks)
        context_check_list = tuple(context_checks)

        def predicate(ctx: _Context) -> bool:
            if arg_name is not None:
                value = ctx.request.args.get(arg_name)
                if value is None:
                    return False
                for arg_check in arg_check_list:
                    if not arg_check(value, ctx):
                        return False
            for context_check in context_check_list:  # noqa: SIM110 (hot path, see matches)
                if not context_check(ctx):
                    return False
            return True

        return predicate, arg_name

    def integrity_value(self, node: Node) -> str:
        value = self.load(node)
        if value not in _INTEGRITY_VALUES:
            raise self.error(node, f"invalid integrity {value!r}; use {sorted(_INTEGRITY_VALUES)}")
        return value

    def integrity_check(self, node: Node) -> Callable[[ArgValue, _Context], bool]:
        want_untrusted = self.integrity_value(node) != "trusted"
        return lambda arg, _ctx: (arg.label.integrity is Integrity.UNTRUSTED) == want_untrusted

    def confidentiality_check(self, node: Node) -> Callable[[ArgValue, _Context], bool]:
        def level(value_node: Node) -> Confidentiality:
            value = self.load(value_node)
            try:
                return Confidentiality[str(value).upper()]
            except KeyError:
                raise self.error(value_node, f"invalid confidentiality {value!r}") from None

        if not isinstance(node, MappingNode):
            exact = level(node)
            return lambda arg, _ctx: arg.label.confidentiality is exact
        bounds = self.mapping(node, "confidentiality", frozenset({"gte", "lte"}))
        low = level(bounds["gte"]) if "gte" in bounds else Confidentiality.PUBLIC
        high = level(bounds["lte"]) if "lte" in bounds else Confidentiality.SECRET
        return lambda arg, _ctx: low <= arg.label.confidentiality <= high

    def value_checks(self, node: Node) -> list[Callable[[ArgValue, _Context], bool]]:
        operators = self.mapping(node, "value", _VALUE_OPERATORS)
        checks: list[Callable[[ArgValue, _Context], bool]] = []
        for op, operand_node in operators.items():
            checks.append(self.value_check(op, operand_node))
        return checks

    def value_check(self, op: str, node: Node) -> Callable[[ArgValue, _Context], bool]:
        if op in _COMPARISONS:
            compare, operand = _COMPARISONS[op], self.scalar_operand(node, op)

            def comparison(arg: ArgValue, _ctx: _Context) -> bool:
                try:
                    return bool(compare(arg.value, operand))
                except TypeError:  # e.g. text compared with a number: the condition does not hold
                    return False

            return comparison
        if op in ("in", "not_in"):
            items = tuple(self.scalar_operand(item, op) for item in self.sequence(node, op))
            negate = op == "not_in"
            return lambda arg, _ctx: (arg.value in items) != negate
        if op == "regex":
            try:
                pattern = re.compile(self.text(node, "regex"))
            except re.error as exc:
                raise self.error(node, f"invalid regex: {exc}") from None
            return lambda arg, _ctx: (
                isinstance(arg.value, str) and bool(pattern.fullmatch(arg.value))
            )
        if op == "startswith":
            prefix = self.text(node, "startswith")
            return lambda arg, _ctx: isinstance(arg.value, str) and arg.value.startswith(prefix)
        expected = self.load(node)  # has_link_outside_allowed_hosts
        if not isinstance(expected, bool):
            raise self.error(node, f"{op} must be true or false")
        return lambda arg, ctx: _has_foreign_link(arg.value, ctx.hosts) == expected


# ---------------------------------------------------------------- evaluation


@dataclass(frozen=True, slots=True)
class _Fired:
    kind: DecisionKind
    rule: str
    arg: str | None
    reason: str


def evaluate(
    request: ToolCallRequest,
    spec: ToolSpec,
    policy: AgentPolicy,
    lookup: RecordLookup | None = None,
) -> Decision:
    """Decide one tool call. Pure: no I/O beyond the optional record lookup."""
    version = policy.version
    if spec.kind == "source":
        return Decision(
            "allow", DEFAULT_RULE, "Reading data is not checked; only actions are.", version
        )

    tool = request.tool
    audience = resolve_audience(spec, {n: a.value for n, a in request.args.items()}, lookup)
    fired = _core_rules(request, spec, audience)
    context = _Context(request, audience, policy.allowed_link_hosts)
    matches = [rule for rule in policy.rules_for(tool) if rule.matches(context)]
    matched = tuple(dict.fromkeys([f.rule for f in fired] + [r.rule_id for r in matches]))

    def from_core(f: _Fired) -> Decision:
        return Decision(f.kind, f.rule, f.reason, version, f.arg, matched)

    def from_rule(rule: CompiledRule) -> Decision:
        return Decision(rule.decision, rule.rule_id, rule.reason, version, rule.arg, matched)

    core = max(fired, key=lambda f: SEVERITY[f.kind], default=None)  # first wins ties: C1, C2, C3
    if core is not None and core.kind == "block":
        return from_core(core)
    for rule in matches:
        if rule.decision == "block":
            return from_rule(rule)
    asks = [rule for rule in matches if rule.decision == "ask"]
    if asks:
        return from_rule(asks[0])
    allow = next((r for r in matches if r.decision == "allow" and r.tool == tool), None)
    if core is not None:  # a core ask: only a named allow relaxes it
        return from_rule(allow) if allow is not None else from_core(core)
    if allow is not None:
        return from_rule(allow)
    return Decision("allow", DEFAULT_RULE, "No rule objected to this call.", version, None, matched)


def _core_rules(request: ToolCallRequest, spec: ToolSpec, audience: Audience) -> list[_Fired]:
    tool = request.tool
    fired: list[_Fired] = []
    proven = [  # critical arguments whose attacker origin is proven: one C1 block names them all
        name
        for name, arg in request.args.items()
        if arg.label.integrity is Integrity.UNTRUSTED
        and spec.is_critical(name)
        and arg.evidence in ("exact", "traced")
    ]
    if proven:
        origin = _describe_sources(join_all(request.args[name].label for name in proven))
        subject, verb, pronoun = (
            (f"The {proven[0]}", "was", "it") if len(proven) == 1
            else (f"The {_and_list(proven)}", "were", "them")
        )  # fmt: skip
        fired.append(
            _Fired(
                "block",
                C1,
                proven[0],
                f"{subject} {verb} written by {origin} (untrusted), "
                f"and {tool} uses {pronoun} to decide what happens.",
            )
        )
    for name, arg in request.args.items():
        if arg.label.integrity is not Integrity.UNTRUSTED or not spec.is_critical(name):
            continue
        source = _describe_sources(arg.label)
        if arg.evidence in ("exact", "traced"):
            continue  # covered by the single C1 block above
        if arg.evidence == "ambiguous":
            fired.append(
                _Fired(
                    "ask",
                    C1,
                    name,
                    f"The {name} matches both trusted data and untrusted text from {source}, "
                    f"so a person should confirm this {tool} call.",
                )
            )
        else:  # inferred: no proof of attacker origin, so ask instead of block
            fired.append(
                _Fired(
                    "ask",
                    C3,
                    name,
                    f"Untrusted content was read earlier and the {name} could not be traced "
                    f"to a trusted source, so a person should approve this {tool} call.",
                )
            )

    if request.args:
        worst_name, worst = max(
            request.args.items(), key=lambda item: item[1].label.confidentiality
        )
        if worst.label.confidentiality > CLEARANCE[audience]:
            fired.append(
                _Fired(
                    "block",
                    C2,
                    worst_name,
                    f"The {worst_name} contains {worst.label.confidentiality.name.lower()} data "
                    f"from {_describe_sources(worst.label)}, but {tool} sends it to "
                    f"a {audience} audience.",
                )
            )

    if request.context.integrity is Integrity.UNTRUSTED and spec.risk == "high":
        fired.append(
            _Fired(
                "ask",
                C3,
                None,
                f"Untrusted content shaped this request, so a person should approve "
                f"this high-risk {tool} call.",
            )
        )
    return fired


_SOURCE_NAMES = {"user": "the user", "planner": "the plan", "system": "our own systems"}


def _describe_sources(label: Label) -> str:
    """Name where a value came from. Outside origins (tool records, MCP tools) are named
    first and alone when present: the plan, the user and our own systems are never the
    attacker, and listing them blurs which source wrote the value."""
    outside = sorted(s for s in label.sources if s not in _SOURCE_NAMES)
    chosen = outside or sorted(label.sources)
    names = [_describe_source(source) for source in chosen]
    if not names:
        return "an unknown source"
    return _and_list(names[:3]) + (" and others" if len(names) > 3 else "")


def _and_list(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _describe_source(source: str) -> str:
    if source.startswith("tool:"):
        tool, _, record = source[len("tool:") :].partition("#")
        return f"{tool} record {record}" if record else f"the {tool} tool"
    if source.startswith("mcp:"):
        return f"MCP tool {source[len('mcp:') :]}"
    return _SOURCE_NAMES.get(source, source)
