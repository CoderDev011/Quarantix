"""F02 tool registry. Spec: docs/features/F02-registry.md, contracts sections 3 and 10.4."""

import time

import pytest

from quarantix.core.labels import Confidentiality, Integrity, Label, trusted
from quarantix.core.registry import (
    ChannelAllowlist,
    DestinationDomain,
    RecordField,
    Registry,
    ToolSpec,
    resolve_audience,
)


def _pay_spec(risk: str = "high") -> ToolSpec:
    return ToolSpec(
        name="pay",
        kind="sink",
        description="Move money.",
        arg_schema={
            "type": "object",
            "properties": {"account": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["account", "amount"],
        },
        risk=risk,  # type: ignore[arg-type]
        audience="internal",
        critical_args=("account", "amount"),
    )


def _lookup_spec() -> ToolSpec:
    return ToolSpec(
        name="lookup",
        kind="source",
        description="Read a record.",
        arg_schema={"type": "object", "properties": {"id": {"type": "string"}}},
        output_label=trusted("system", Confidentiality.PRIVATE),
        endorses_output=True,
    )


# ---------------------------------------------------------------- registration and lookup


def test_registered_spec_is_returned_unchanged() -> None:
    registry = Registry()
    registry.register(_pay_spec())
    spec = registry.get("pay")
    assert (spec.kind, spec.risk, spec.critical_args) == ("sink", "high", ("account", "amount"))


def test_unknown_tool_gets_the_default_deny_spec() -> None:
    spec = Registry().get("never_registered")
    assert spec.name == "never_registered"
    assert (spec.kind, spec.risk, spec.audience) == ("sink", "high", "external")
    assert spec.critical_args == ("*",)
    assert spec.is_critical("anything")


def test_identical_duplicate_registration_is_accepted() -> None:
    registry = Registry()
    registry.register(_pay_spec())
    registry.register(_pay_spec())
    assert registry.names() == ["pay"]


def test_conflicting_duplicate_registration_is_rejected() -> None:
    registry = Registry()
    registry.register(_pay_spec())
    with pytest.raises(ValueError, match="pay"):
        registry.register(_pay_spec(risk="low"))


def test_critical_argument_must_exist_in_the_schema() -> None:
    with pytest.raises(ValueError, match="amout"):
        ToolSpec(
            name="pay",
            kind="sink",
            description="Move money.",
            arg_schema={"type": "object", "properties": {"amount": {"type": "number"}}},
            critical_args=("amout",),
        )


def test_invalid_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="kind"):
        ToolSpec(name="x", kind="faucet", description="d", arg_schema={})  # type: ignore[arg-type]


# ---------------------------------------------------------------- registering Python functions


def test_decorator_builds_the_schema_from_type_hints() -> None:
    registry = Registry()

    @registry.tool(kind="sink", risk="medium", critical_args=("channel",))
    def send(channel: str, text: str, urgent: bool = False) -> None:
        """Send a message."""

    schema = registry.get("send").arg_schema
    assert schema["properties"]["channel"]["type"] == "string"
    assert schema["properties"]["urgent"]["type"] == "boolean"
    assert sorted(schema["required"]) == ["channel", "text"]


def test_decorator_maps_float_to_number_and_uses_the_docstring() -> None:
    registry = Registry()

    @registry.tool(kind="sink")
    def pay(amount: float) -> None:
        """Move money."""

    spec = registry.get("pay")
    assert spec.arg_schema["properties"]["amount"]["type"] == "number"
    assert spec.description == "Move money."


def test_decorator_returns_the_original_function() -> None:
    registry = Registry()

    def ping() -> str:
        """Ping."""
        return "pong"

    assert registry.tool(kind="source")(ping) is ping
    assert registry.get("ping").fn is ping


def test_decorator_requires_a_description() -> None:
    registry = Registry()
    with pytest.raises(ValueError, match="description"):

        @registry.tool(kind="source")
        def undocumented() -> None:
            pass


def test_decorator_rejects_variadic_parameters() -> None:
    registry = Registry()
    with pytest.raises(ValueError, match="args"):

        @registry.tool(kind="sink")
        def anything(*args: str) -> None:
            """Accepts anything."""


# ---------------------------------------------------------------- catalog and version


def test_catalog_is_sorted_and_has_no_functions() -> None:
    registry = Registry()
    registry.register(_pay_spec())
    registry.register(_lookup_spec())
    catalog = registry.catalog()
    assert [entry["name"] for entry in catalog] == ["lookup", "pay"]
    assert set(catalog[0]) == {"name", "description", "kind", "arg_schema"}


def test_version_does_not_depend_on_registration_order() -> None:
    first, second = Registry(), Registry()
    first.register(_pay_spec())
    first.register(_lookup_spec())
    second.register(_lookup_spec())
    second.register(_pay_spec())
    assert first.version == second.version
    assert len(first.version) == 12


def test_version_changes_when_a_label_or_risk_changes() -> None:
    low, high = Registry(), Registry()
    low.register(_pay_spec(risk="low"))
    high.register(_pay_spec(risk="high"))
    assert low.version != high.version


def test_version_is_cached_until_the_next_registration() -> None:
    registry = Registry()
    registry.register(_pay_spec())
    before = registry.version
    assert registry.version is before
    registry.register(_lookup_spec())
    assert registry.version != before


# ---------------------------------------------------------------- audience resolution


def _send_spec(audience: object) -> ToolSpec:
    return ToolSpec(
        name="send",
        kind="sink",
        description="Send.",
        arg_schema={"type": "object", "properties": {"to": {"type": "string"}}},
        audience=audience,  # type: ignore[arg-type]
        critical_args=("to",),
    )


def test_fixed_audience_is_returned_as_is() -> None:
    assert resolve_audience(_send_spec("self"), {"to": "x"}) == "self"


def test_channel_allowlist_rule() -> None:
    spec = _send_spec(ChannelAllowlist(param="to", known=frozenset({"#team-log"})))
    assert resolve_audience(spec, {"to": "#team-log"}) == "internal"
    assert resolve_audience(spec, {"to": "https://hooks.example.org/x"}) == "external"


@pytest.mark.parametrize(
    ("destination", "audience"),
    [
        ("pat@company.example", "internal"),
        ("pat@mail.company.example", "internal"),
        ("https://wiki.company.example/page", "internal"),
        ("pat@evil.example", "external"),
        ("https://company.example.evil.example/x", "external"),
    ],
)
def test_destination_domain_rule(destination: str, audience: str) -> None:
    spec = _send_spec(DestinationDomain(param="to", org_domains=frozenset({"company.example"})))
    assert resolve_audience(spec, {"to": destination}) == audience


def test_record_field_rule_maps_a_looked_up_field() -> None:
    rule = RecordField(
        store="spaces",
        id_param="to",
        field="visibility",
        mapping={"public": "public", "private": "internal"},
    )
    records = {
        ("spaces", "a"): {"visibility": "public"},
        ("spaces", "b"): {"visibility": "private"},
    }
    spec = _send_spec(rule)

    def lookup(store: str, record_id: str) -> dict | None:
        return records.get((store, record_id))

    assert resolve_audience(spec, {"to": "a"}, lookup) == "public"
    assert resolve_audience(spec, {"to": "b"}, lookup) == "internal"


@pytest.mark.parametrize("args", [{"to": "missing"}, {}, {"to": None}])
def test_failed_audience_lookup_falls_back_to_external(args: dict) -> None:
    rule = RecordField(store="spaces", id_param="to", field="visibility", mapping={})
    spec = _send_spec(rule)
    assert resolve_audience(spec, args, lambda store, record_id: None) == "external"
    assert resolve_audience(spec, args) == "external"  # no lookup available at all


def test_output_labels_survive_registration() -> None:
    registry = Registry()
    registry.register(_lookup_spec())
    spec = registry.get("lookup")
    assert spec.output_label == trusted("system", Confidentiality.PRIVATE)
    assert spec.endorses_output


def test_default_output_label_is_untrusted_internal() -> None:
    spec = ToolSpec(name="r", kind="source", description="d", arg_schema={})
    assert spec.output_label == Label(Integrity.UNTRUSTED, Confidentiality.INTERNAL, frozenset())


@pytest.mark.perf
def test_lookup_is_constant_time() -> None:
    registry = Registry()
    for i in range(1000):
        registry.register(ToolSpec(name=f"t{i}", kind="source", description="d", arg_schema={}))
    start = time.perf_counter()
    for i in range(100_000):
        registry.get(f"t{i % 1000}")
    per_lookup = (time.perf_counter() - start) / 100_000
    print(f"\nregistry lookup: {per_lookup * 1e9:.0f} ns")
    assert per_lookup < 2e-6
