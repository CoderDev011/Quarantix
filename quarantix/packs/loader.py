"""Domain-pack loader (F03, contracts section 10).

`load_domain(path)` reads `domains/<name>/`, validates it, and returns an
immutable `Domain`. Any problem raises `PackError` naming the file, the line
(when known) and the tool, store or field at fault. Labels for source tools
are derived from the store definitions, so the rule "text written by outsiders
is untrusted" holds by construction; explicit labels are allowed but checked.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from quarantix.core.labels import Confidentiality, Integrity, Label
from quarantix.core.plan import PlanError, parse_plan
from quarantix.core.plan_validate import validate_plan
from quarantix.core.registry import (
    AUDIENCES,
    AudienceRule,
    ChannelAllowlist,
    DestinationDomain,
    RecordField,
    Registry,
    ToolSpec,
)
from quarantix.engine.policy import PolicyError, compile_pack
from quarantix.packs.model import (
    BEHAVIOR_KIND,
    GOAL_KINDS,
    Attack,
    AttackerMarkers,
    BenignTask,
    Domain,
    FieldSpec,
    Goal,
    Plant,
    PlantTarget,
    StoreSpec,
    Task,
    ToolManifest,
)
from quarantix.packs.world import Seed

SCHEMA_VERSION = 1
MONEY_WORDS = ("amount", "price", "total", "wage", "fee", "balance")  # or type: money
PARAM_TYPES: Mapping[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "integer": {"type": "integer"},
    "number": {"type": "number"},
    "money": {"type": "number"},
    "boolean": {"type": "boolean"},
}
# Reserved names (RFC 2606 / 6761) plus the local attacker server: nothing real.
FAKE_SUFFIXES = (".test", ".example", ".invalid", ".localhost")
FAKE_DOMAINS = frozenset({"example.com", "example.org", "example.net", "attacker", "localhost"})
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_URL_HOST = re.compile(r"https?://([^/\s:?#\"'<>]+)", re.IGNORECASE)
_REQUIRED_CONFIG: Mapping[str, tuple[str, ...]] = {
    "list_records": ("store",),
    "get_record": ("store", "id_param"),
    "read_secret": ("store", "name_param"),
    "fetch_page": ("store",),
    "ledger_write": ("ledger",),
    "post_internal": ("ledger", "channel_param", "channels"),
    "send_external": ("ledger", "destination_param"),
    "run_command": ("ledger",),
}
_DOMAIN_KEYS = frozenset(
    {
        "schema_version", "name", "title", "description", "agent", "system_prompt", "org_domains",
        "attacker", "stores", "tools", "goals", "tasks",
    }
)  # fmt: skip
_TOOL_KEYS = frozenset(
    {
        "name", "description", "behavior", "config", "parameters", "output_label",
        "field_labels", "endorses_output", "audience", "risk", "critical_args",
    }
)  # fmt: skip


class PackError(ValueError):
    def __init__(self, message: str, file: str | None = None, line: int | None = None) -> None:
        where = file or "pack"
        if line is not None:
            where += f":{line}"
        super().__init__(f"{where}: {message}")
        self.file = file
        self.line = line


# ---------------------------------------------------------------- YAML with line numbers


class _LineLoader(yaml.SafeLoader):
    lines: dict[int, int]


def _construct_map(loader: _LineLoader, node: yaml.MappingNode) -> Iterator[dict[Any, Any]]:
    data: dict[Any, Any] = {}
    loader.lines[id(data)] = node.start_mark.line + 1
    yield data
    data.update(loader.construct_mapping(node))


_LineLoader.add_constructor("tag:yaml.org,2002:map", _construct_map)


class _Doc:
    """A parsed YAML file that remembers each mapping's line, for error messages."""

    def __init__(self, path: Path) -> None:
        self.file = path.as_posix()
        text = path.read_text(encoding="utf-8")
        loader = _LineLoader(text)
        loader.lines = {}
        try:
            self.data = loader.get_single_data()
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark else None
            raise PackError(f"invalid YAML: {exc}", self.file, line) from None
        finally:
            loader.dispose()
        self.lines = loader.lines
        self.text = text

    def error(self, message: str, node: Any = None) -> PackError:
        return PackError(message, self.file, self.lines.get(id(node)) if node is not None else None)

    def mapping(
        self, node: Any, what: str, allowed: frozenset[str] | None = None
    ) -> dict[str, Any]:
        if not isinstance(node, dict):
            raise self.error(f"{what} must be a mapping", node)
        if allowed is not None:
            unknown = sorted(set(map(str, node)) - allowed)
            if unknown:
                raise self.error(f"{what}: unknown key(s) {unknown}", node)
        return node

    def require(self, node: dict[str, Any], key: str, what: str) -> Any:
        if key not in node or node[key] in (None, ""):
            raise self.error(f"{what}: '{key}' is required", node)
        return node[key]


# ---------------------------------------------------------------- entry point


def load_domain(path: str | Path) -> Domain:
    root = Path(path)
    doc = _Doc(root / "domain.yaml")
    top = doc.mapping(doc.data, "domain.yaml", _DOMAIN_KEYS)
    if top.get("schema_version") != SCHEMA_VERSION:
        raise doc.error(f"schema_version must be {SCHEMA_VERSION}", top)
    name = str(doc.require(top, "name", "domain"))
    if name != root.name:
        raise doc.error(f"name {name!r} must match the folder name {root.name!r}", top)

    org_domains = frozenset(str(d).lower() for d in top.get("org_domains") or ())
    attacker = _attacker(doc, top.get("attacker"))
    stores = _stores(doc, top.get("stores"))
    seed = _seed(root, stores)
    tools = _tools(doc, top.get("tools"), stores, org_domains)
    registry = Registry()
    for manifest in tools.values():
        registry.register(manifest.spec)
    ledgers = frozenset(str(m.config["ledger"]) for m in tools.values() if m.spec.kind == "sink")

    policy_text, policy = _policy(root / "policy.yaml")
    day_one_path = root / "policy.day-one.yaml"
    day_one_text = _policy(day_one_path)[0] if day_one_path.exists() else policy_text

    goals = _goals(doc, top.get("goals"), stores, ledgers, tools)
    tasks = _tasks(doc, top.get("tasks"), stores)
    plans = _plans(root, tasks, registry)
    attacks = tuple(_attacks(root, name, tasks, goals, stores))
    benign = tuple(_benign(root, name, tasks, stores))

    return Domain(
        name=name,
        title=str(top.get("title") or name),
        description=str(top.get("description") or ""),
        agent=str(doc.require(top, "agent", "domain")),
        system_prompt=str(top.get("system_prompt") or ""),
        org_domains=org_domains,
        attacker=attacker,
        stores=MappingProxyType(stores),
        tools=MappingProxyType(tools),
        registry=registry,
        ledgers=ledgers,
        goals=MappingProxyType(goals),
        tasks=MappingProxyType(tasks),
        plans=MappingProxyType(plans),
        policy_text=policy_text,
        policy=policy,
        day_one_text=day_one_text,
        attacks=attacks,
        benign=benign,
        capabilities=capabilities(tools),
        seed=seed,
        allowed_link_hosts=policy.allowed_link_hosts | org_domains,
    )


def load_all(root: str | Path) -> dict[str, Domain]:
    """Every pack under `root` (each folder with a domain.yaml), by name."""
    base = Path(root)
    return {p.name: load_domain(p) for p in sorted(base.iterdir()) if (p / "domain.yaml").is_file()}


# ---------------------------------------------------------------- sections


def _attacker(doc: _Doc, node: Any) -> AttackerMarkers:
    node = doc.mapping(
        node, "attacker", frozenset({"host", "aliases", "account", "email", "values"})
    )
    values = tuple(float(v) for v in node.get("values") or ())
    return AttackerMarkers(
        host=str(doc.require(node, "host", "attacker")).lower(),
        aliases=tuple(str(a).lower() for a in node.get("aliases") or ()),
        account=str(doc.require(node, "account", "attacker")),
        email=str(doc.require(node, "email", "attacker")).lower(),
        values=values,
    )


def _confidentiality(doc: _Doc, value: Any, node: Any, what: str) -> Confidentiality:
    try:
        return Confidentiality[str(value).upper()]
    except KeyError:
        raise doc.error(f"{what}: invalid confidentiality {value!r}", node) from None


def _stores(doc: _Doc, node: Any) -> dict[str, StoreSpec]:
    if not isinstance(node, list) or not node:
        raise doc.error("stores must be a non-empty list")
    stores: dict[str, StoreSpec] = {}
    for item in node:
        item = doc.mapping(item, "store", frozenset({"name", "id_field", "authored_by", "fields"}))
        name = str(doc.require(item, "name", "store"))
        authored = str(doc.require(item, "authored_by", f"store {name}"))
        if authored not in ("outsider", "system"):
            raise doc.error(f"store {name}: authored_by must be outsider or system", item)
        fields_node = doc.mapping(doc.require(item, "fields", f"store {name}"), f"store {name}")
        fields: dict[str, FieldSpec] = {}
        for field_name, spec in fields_node.items():
            spec = doc.mapping(
                spec or {}, f"store {name} field {field_name}",
                frozenset({"type", "confidentiality", "text"}),
            )  # fmt: skip
            fields[str(field_name)] = FieldSpec(
                type=str(spec.get("type", "string")),
                confidentiality=_confidentiality(
                    doc, spec.get("confidentiality", "internal"), spec, f"store {name}"
                ),
                text=bool(spec.get("text", False)),
            )
        id_field = str(doc.require(item, "id_field", f"store {name}"))
        if id_field not in fields:
            raise doc.error(f"store {name}: id_field {id_field!r} is not a field", item)
        if name in stores:
            raise doc.error(f"duplicate store {name!r}", item)
        stores[name] = StoreSpec(name, id_field, authored, MappingProxyType(fields))  # type: ignore[arg-type]
    return stores


def _seed(root: Path, stores: Mapping[str, StoreSpec]) -> Seed:
    rows_by_store: dict[str, list[dict[str, Any]]] = {}
    for name, spec in stores.items():
        path = root / "seed" / f"{name}.json"
        rows: list[dict[str, Any]] = []
        if path.exists():
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise PackError(f"invalid JSON: {exc.msg}", path.as_posix(), exc.lineno) from None
        if not isinstance(rows, list):
            raise PackError("seed must be a list of records", path.as_posix())
        seen: set[str] = set()
        for i, row in enumerate(rows):
            where = f"record {i + 1}"
            if not isinstance(row, dict):
                raise PackError(f"{where} must be an object", path.as_posix())
            unknown = sorted(set(row) - set(spec.fields))
            if unknown:
                raise PackError(
                    f"{where}: fields {unknown} are not in store {name}", path.as_posix()
                )
            if spec.id_field not in row:
                raise PackError(f"{where}: missing id field {spec.id_field!r}", path.as_posix())
            record_id = str(row[spec.id_field])
            if record_id in seen:
                raise PackError(f"{where}: duplicate id {record_id!r}", path.as_posix())
            seen.add(record_id)
            for value in row.values():
                if isinstance(value, dict | list):
                    raise PackError(f"{where}: values must be scalars", path.as_posix())
                if isinstance(value, str):
                    _check_fake(value, path.as_posix(), where)
        rows_by_store[name] = rows
    return Seed.build(rows_by_store, {n: s.id_field for n, s in stores.items()})


def _check_fake(text: str, file: str, where: str) -> None:
    hosts = [m.group(1) for m in _EMAIL.finditer(text)] + [
        m.group(1) for m in _URL_HOST.finditer(text)
    ]
    for host in hosts:
        host = host.lower().rstrip(".")
        if host in FAKE_DOMAINS or host.endswith(FAKE_SUFFIXES):
            continue
        if any(host.endswith("." + d) for d in FAKE_DOMAINS):
            continue
        raise PackError(f"{where}: {host!r} is not a reserved fake domain", file)


def _label(doc: _Doc, node: Any, what: str, source: str) -> Label:
    node = doc.mapping(node, what, frozenset({"integrity", "confidentiality"}))
    integrity = str(node.get("integrity", "untrusted")).upper()
    if integrity not in Integrity.__members__:
        raise doc.error(f"{what}: invalid integrity {node.get('integrity')!r}", node)
    return Label(
        Integrity[integrity],
        _confidentiality(doc, node.get("confidentiality", "internal"), node, what),
        frozenset({source}),
    )


def _derived_labels(store: StoreSpec, tool_source: str) -> tuple[Label, dict[str, Label]]:
    """Record label and per-field labels from a store definition (outsider text = untrusted)."""

    def field_label(spec: FieldSpec) -> Label:
        untrusted = store.authored_by == "outsider" and spec.text
        integrity = Integrity.UNTRUSTED if untrusted else Integrity.TRUSTED
        return Label(integrity, spec.confidentiality, frozenset({tool_source}))

    labels = {name: field_label(spec) for name, spec in store.fields.items()}
    floor = min(spec.confidentiality for spec in store.fields.values())
    record = Label(Integrity.TRUSTED, floor, frozenset({tool_source}))
    return record, {name: lab for name, lab in labels.items() if lab != record}


def _tools(
    doc: _Doc, node: Any, stores: Mapping[str, StoreSpec], org_domains: frozenset[str]
) -> dict[str, ToolManifest]:
    if not isinstance(node, list) or not node:
        raise doc.error("tools must be a non-empty list")
    tools: dict[str, ToolManifest] = {}
    for item in node:
        item = doc.mapping(item, "tool", _TOOL_KEYS)
        name = str(doc.require(item, "name", "tool"))
        what = f"tool {name}"
        behavior = str(doc.require(item, "behavior", what))
        if behavior not in BEHAVIOR_KIND:
            raise doc.error(f"{what}: unknown behavior {behavior!r}", item)
        kind = BEHAVIOR_KIND[behavior]
        config = doc.mapping(item.get("config") or {}, f"{what} config")
        missing = [k for k in _REQUIRED_CONFIG[behavior] if k not in config]
        if missing:
            raise doc.error(f"{what}: behavior {behavior} needs config {missing}", item)

        params_node = doc.mapping(item.get("parameters") or {}, f"{what} parameters")
        properties: dict[str, Any] = {}
        required: list[str] = []
        param_types: dict[str, str] = {}
        for param, spec in params_node.items():
            spec = doc.mapping(
                spec or {}, f"{what} parameter {param}",
                frozenset({"type", "description", "enum", "pattern", "default", "required"}),
            )  # fmt: skip
            ptype = str(spec.get("type", "string"))
            if ptype not in PARAM_TYPES:
                raise doc.error(f"{what}: parameter {param} has unknown type {ptype!r}", spec)
            schema = dict(PARAM_TYPES[ptype])
            for key in ("description", "enum", "pattern", "default"):
                if key in spec:
                    schema[key] = spec[key]
            properties[str(param)] = schema
            param_types[str(param)] = ptype
            if spec.get("required", "default" not in spec):
                required.append(str(param))
        arg_schema = {"type": "object", "properties": properties, "required": required}

        _check_config_refs(doc, item, what, behavior, config, stores, properties)

        tool_source = f"tool:{name}"
        store = stores.get(str(config.get("store", "")))
        if kind == "sink":
            output, field_labels = (
                Label(Integrity.TRUSTED, Confidentiality.PUBLIC, frozenset({tool_source})),
                {},
            )
        elif behavior == "read_secret":
            output, field_labels = (
                Label(Integrity.TRUSTED, Confidentiality.SECRET, frozenset({tool_source})),
                {},
            )
        elif behavior == "fetch_page":
            output, field_labels = (
                Label(Integrity.UNTRUSTED, Confidentiality.PUBLIC, frozenset({tool_source})),
                {},
            )
        else:
            assert store is not None
            output, field_labels = _derived_labels(store, tool_source)
        if "output_label" in item:
            output = _label(doc, item["output_label"], f"{what} output_label", tool_source)
        for field, spec in doc.mapping(
            item.get("field_labels") or {}, f"{what} field_labels"
        ).items():
            field_labels[str(field)] = _label(doc, spec, f"{what} field {field}", tool_source)

        _check_labels(doc, item, what, behavior, store, output, field_labels)

        critical = tuple(str(a) for a in item.get("critical_args") or ())
        risk = str(item.get("risk", "low" if kind == "source" else "high"))
        audience = _audience(doc, item, what, behavior, config, org_domains)
        try:
            spec = ToolSpec(
                name=name,
                kind=kind,  # type: ignore[arg-type]
                description=str(doc.require(item, "description", what)),
                arg_schema=arg_schema,
                output_label=output,
                field_labels=MappingProxyType(field_labels),
                endorses_output=bool(item.get("endorses_output", False)),
                audience=audience,
                risk=risk,  # type: ignore[arg-type]
                critical_args=critical,
            )
        except ValueError as exc:
            raise doc.error(str(exc), item) from None

        if kind == "sink":
            _check_sink(doc, item, what, behavior, config, spec, param_types)
        if name in tools:
            raise doc.error(f"duplicate tool {name!r}", item)
        tools[name] = ToolManifest(
            spec,
            behavior,  # type: ignore[arg-type]
            MappingProxyType(dict(config)),
            tuple(properties),
            frozenset(required),  # type: ignore[arg-type]
        )
    return tools


def _check_config_refs(
    doc: _Doc,
    item: Any,
    what: str,
    behavior: str,
    config: Mapping[str, Any],
    stores: Mapping[str, StoreSpec],
    params: Mapping[str, Any],
) -> None:
    if "store" in config:
        store = stores.get(str(config["store"]))
        if store is None:
            raise doc.error(f"{what}: unknown store {config['store']!r}", item)
        for param, field in (config.get("filters") or {}).items():
            if param not in params or field not in store.fields:
                raise doc.error(
                    f"{what}: filter {param}->{field} needs that parameter and field", item
                )
        owner_field = config.get("owner_field")
        if owner_field is not None and (
            owner_field not in store.fields or config.get("owner_param") not in params
        ):
            raise doc.error(f"{what}: the owner check needs owner_field and owner_param", item)
    for key in ("id_param", "name_param", "channel_param", "destination_param", "limit_param"):
        if key in config and config[key] not in params:
            raise doc.error(f"{what}: {key} {config[key]!r} is not a parameter", item)
    if behavior == "fetch_page" and config.get("url_param", "url") not in params:
        raise doc.error(f"{what}: fetch_page needs a url parameter", item)
    if behavior == "run_command" and config.get("command_param", "command") not in params:
        raise doc.error(f"{what}: run_command needs a command parameter", item)


def _check_labels(
    doc: _Doc,
    item: Any,
    what: str,
    behavior: str,
    store: StoreSpec | None,
    output: Label,
    field_labels: Mapping[str, Label],
) -> None:
    """Rule 2: text of outsider-authored stores must reach the agent labeled untrusted."""
    if behavior == "read_secret" and output.confidentiality is not Confidentiality.SECRET:
        raise doc.error(f"{what}: read_secret output must be labeled secret", item)
    if store is None or store.authored_by != "outsider":
        return
    if behavior == "fetch_page":
        if output.integrity is not Integrity.UNTRUSTED:
            raise doc.error(
                f"{what}: pages from outsider store {store.name} must be untrusted", item
            )
        return
    for field, spec in store.fields.items():
        if not spec.text:
            continue
        label = field_labels.get(field, output)
        if label.integrity is not Integrity.UNTRUSTED:
            raise doc.error(
                f"{what}: field {field!r} of outsider store {store.name!r} is free text "
                f"and must be labeled untrusted",
                item,
            )


def _audience(
    doc: _Doc,
    item: Any,
    what: str,
    behavior: str,
    config: Mapping[str, Any],
    org_domains: frozenset[str],
) -> Any:
    node = item.get("audience")
    if node is None:
        if behavior == "post_internal":
            node = {"rule": "channel_allowlist"}
        elif behavior == "send_external":
            node = {"rule": "destination_domain"} if org_domains else "external"
        else:
            return "external" if BEHAVIOR_KIND[behavior] == "sink" else "self"
    if isinstance(node, str):
        if node not in AUDIENCES:
            raise doc.error(f"{what}: invalid audience {node!r}", item)
        return node
    node = doc.mapping(node, f"{what} audience")
    rule = node.get("rule")
    result: AudienceRule
    if rule == "channel_allowlist":
        result = ChannelAllowlist(
            param=str(node.get("param", config.get("channel_param", "channel"))),
            known=frozenset(str(c) for c in node.get("known", config.get("channels", ()))),
        )
    elif rule == "destination_domain":
        result = DestinationDomain(
            param=str(node.get("param", config.get("destination_param", "to"))),
            org_domains=frozenset(str(d).lower() for d in node.get("org", org_domains)),
        )
    elif rule == "record_field":
        mapping = {str(k): str(v) for k, v in (node.get("map") or {}).items()}
        if any(v not in AUDIENCES for v in mapping.values()):
            raise doc.error(f"{what}: record_field map has an invalid audience", node)
        result = RecordField(
            store=str(doc.require(node, "store", f"{what} audience")),
            id_param=str(doc.require(node, "id_param", f"{what} audience")),
            field=str(doc.require(node, "field", f"{what} audience")),
            mapping=MappingProxyType(mapping),  # type: ignore[arg-type]
        )
    else:
        raise doc.error(f"{what}: unknown audience rule {rule!r}", node)
    return result


def _check_sink(
    doc: _Doc,
    item: Any,
    what: str,
    behavior: str,
    config: Mapping[str, Any],
    spec: ToolSpec,
    param_types: Mapping[str, str],
) -> None:
    if spec.risk not in ("medium", "high"):  # rule 3
        raise doc.error(f"{what}: a sink must have risk medium or high", item)
    if not spec.critical_args:
        raise doc.error(f"{what}: a sink needs at least one critical argument", item)
    for param, ptype in param_types.items():  # rule 4
        money_like = ptype == "money" or any(word in param.lower() for word in MONEY_WORDS)
        if money_like and not spec.is_critical(param):
            raise doc.error(f"{what}: money-like argument {param!r} must be critical", item)
    key = {"send_external": "destination_param", "post_internal": "channel_param"}.get(behavior)
    if key and not spec.is_critical(str(config[key])):  # rule 5
        raise doc.error(f"{what}: argument {config[key]!r} (destination) must be critical", item)


def _policy(path: Path) -> tuple[str, Any]:
    if not path.exists():
        raise PackError("policy.yaml is required", path.as_posix())
    text = path.read_text(encoding="utf-8")
    try:
        return text, compile_pack(text)
    except PolicyError as exc:
        raise PackError(str(exc), path.as_posix(), exc.line) from None


def _goals(
    doc: _Doc,
    node: Any,
    stores: Mapping[str, StoreSpec],
    ledgers: frozenset[str],
    tools: Mapping[str, ToolManifest],
) -> dict[str, Goal]:
    goals: dict[str, Goal] = {}
    for item in node or ():
        item = doc.mapping(item, "goal", frozenset({"id", "kind", "title", "params", "points"}))
        goal_id = str(doc.require(item, "id", "goal"))
        kind = str(doc.require(item, "kind", f"goal {goal_id}"))
        if kind not in GOAL_KINDS:
            raise doc.error(f"goal {goal_id}: unknown kind {kind!r}", item)
        params = doc.mapping(item.get("params") or {}, f"goal {goal_id} params")
        for ledger in [
            *params.get("ledgers", ()),
            *([params["ledger"]] if "ledger" in params else []),
        ]:
            if ledger not in ledgers:
                raise doc.error(f"goal {goal_id}: unknown ledger {ledger!r}", item)
        refs = [params.get("store"), (params.get("genuine") or {}).get("store")]
        refs += [s.get("store") for s in [*params.get("private", ()), *params.get("public", ())]]
        for store in refs:
            if store is not None and store not in stores:
                raise doc.error(f"goal {goal_id}: unknown store {store!r}", item)
        goals[goal_id] = Goal(
            goal_id, kind, str(item.get("title") or goal_id), MappingProxyType(params),  # type: ignore[arg-type]
            float(item.get("points", 1.0)),
        )  # fmt: skip
    if not goals:
        raise doc.error("a domain needs at least one goal")
    return goals


def _tasks(doc: _Doc, node: Any, stores: Mapping[str, StoreSpec]) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    for item in node or ():
        item = doc.mapping(item, "task", frozenset({"id", "request", "plan", "plant"}))
        task_id = str(doc.require(item, "id", "task"))
        plant = doc.mapping(
            doc.require(item, "plant", f"task {task_id}"), f"task {task_id} plant",
            frozenset({"store", "field", "record", "new_id", "defaults"}),
        )  # fmt: skip
        store = str(doc.require(plant, "store", f"task {task_id} plant"))
        field = str(doc.require(plant, "field", f"task {task_id} plant"))
        if store not in stores or field not in stores[store].fields:  # rule 8
            raise doc.error(f"task {task_id}: plant target {store}.{field} does not exist", plant)
        tasks[task_id] = Task(
            task_id,
            str(doc.require(item, "request", f"task {task_id}")),
            str(item.get("plan") or task_id),
            PlantTarget(
                store, field, str(plant.get("record", "new")), plant.get("new_id"),
                MappingProxyType(dict(plant.get("defaults") or {})),
            ),
        )  # fmt: skip
    if not tasks:
        raise doc.error("a domain needs at least one task")
    return tasks


def _plans(root: Path, tasks: Mapping[str, Task], registry: Registry) -> dict[str, Any]:
    plans: dict[str, Any] = {}
    for task in tasks.values():
        path = root / "plans" / f"{task.plan}.json"
        if not path.exists():
            raise PackError(f"task {task.id}: pinned plan {task.plan!r} not found", path.as_posix())
        try:
            plan = parse_plan(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, PlanError) as exc:
            raise PackError(f"invalid plan: {exc}", path.as_posix()) from None
        issues = validate_plan(plan, registry)  # rule 6
        if issues:
            raise PackError(
                "plan fails validation: " + "; ".join(map(str, issues)), path.as_posix()
            )
        plans[task.plan] = plan
    return plans


def _plant(doc: _Doc, node: Any, what: str, stores: Mapping[str, StoreSpec]) -> Plant:
    node = doc.mapping(node, f"{what} plant", frozenset({"store", "record", "field", "payload"}))
    store = str(doc.require(node, "store", f"{what} plant"))
    field = str(doc.require(node, "field", f"{what} plant"))
    if store not in stores or field not in stores[store].fields:
        raise doc.error(f"{what}: plant target {store}.{field} does not exist", node)
    return Plant(
        store, str(node.get("record", "new")), field, str(doc.require(node, "payload", what))
    )


def _attacks(
    root: Path,
    domain: str,
    tasks: Mapping[str, Task],
    goals: Mapping[str, Goal],
    stores: Mapping[str, StoreSpec],
) -> Iterator[Attack]:
    keys = frozenset(
        {"id", "domain", "technique", "template_id", "plant", "task_id", "goal_id", "notes"}
    )
    for path in sorted((root / "attacks").glob("*.yaml")):
        doc = _Doc(path)
        item = doc.mapping(doc.data, "attack", keys)
        attack_id = str(doc.require(item, "id", "attack"))
        task_id = str(doc.require(item, "task_id", attack_id))
        goal_id = str(doc.require(item, "goal_id", attack_id))
        if task_id not in tasks or goal_id not in goals:
            raise doc.error(f"attack {attack_id}: unknown task or goal", item)
        yield Attack(
            id=attack_id,
            domain=str(item.get("domain", domain)),
            technique=str(doc.require(item, "technique", attack_id)),
            task_id=task_id,
            goal_id=goal_id,
            plant=_plant(doc, item.get("plant"), attack_id, stores),
            template_id=item.get("template_id"),
            notes=str(item.get("notes") or ""),
        )


def _benign(
    root: Path, domain: str, tasks: Mapping[str, Task], stores: Mapping[str, StoreSpec]
) -> Iterator[BenignTask]:
    keys = frozenset({"id", "domain", "task_id", "plant", "expected", "notes"})
    for path in sorted((root / "benign").glob("*.yaml")):
        doc = _Doc(path)
        item = doc.mapping(doc.data, "benign task", keys)
        benign_id = str(doc.require(item, "id", "benign task"))
        task_id = str(doc.require(item, "task_id", benign_id))
        if task_id not in tasks:
            raise doc.error(f"benign {benign_id}: unknown task {task_id!r}", item)
        expected = item.get("expected") or []
        if not isinstance(expected, list):
            raise doc.error(f"benign {benign_id}: expected must be a list", item)
        plant = _plant(doc, item["plant"], benign_id, stores) if item.get("plant") else None
        yield BenignTask(
            benign_id, str(item.get("domain", domain)), task_id, tuple(expected), plant,
            str(item.get("notes") or ""),
        )  # fmt: skip


# ---------------------------------------------------------------- capability index


def capabilities(tools: Mapping[str, ToolManifest]) -> frozenset[str]:
    """What attack templates may require of this domain (used by the red-team filler)."""
    caps: set[str] = set()
    for m in tools.values():
        spec = m.spec
        caps.add(f"behavior:{m.behavior}")
        if spec.kind != "sink":
            continue
        caps.add("sink")
        schema = spec.arg_schema.get("properties", {})
        for param in schema:
            money_like = any(w in param.lower() for w in MONEY_WORDS)
            if money_like and spec.is_critical(param):
                caps.add("money_sink")
        audience = spec.audience
        if audience == "public" or (
            isinstance(audience, RecordField) and "public" in audience.mapping.values()
        ):
            caps.add("public_sink")
        if m.behavior in ("send_external", "run_command") or (m.behavior == "post_internal"):
            caps.add("exfil_sink")
    if any(m.behavior == "read_secret" for m in tools.values()):
        caps.add("read_secret")
    if any(m.behavior == "post_internal" for m in tools.values()):
        caps.add("post_internal")
    return frozenset(caps)
