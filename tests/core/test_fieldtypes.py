"""Reader field types (contracts section 4). Shared by the plan validator and the reader."""

import pytest

from quarantix.core.fieldtypes import parse_field_type


@pytest.mark.parametrize(
    ("spec", "good", "bad"),
    [
        ("bool", True, "yes"),
        ("int", 7, 7.5),
        ("number", 7.5, "7.5"),
        ("money(0,2000)", 120.0, 4999.0),
        ("email", "pat@company.example", "not an email"),
        ("url", "https://company.example/x", "ftp://company.example/x"),
        ("pattern:^N-[0-9]{4}$", "N-1001", "N-1001 and more"),
        ("enum:api|worker", "api", "database"),
        ("short_text", "fine", "x" * 81),
        ("text:5", "short", "too long"),
    ],
)
def test_each_type_keeps_good_values_and_nulls_bad_ones(
    spec: str, good: object, bad: object
) -> None:
    field = parse_field_type(spec)
    assert field.coerce(good) == good
    assert field.coerce(bad) is None
    assert field.coerce(None) is None


def test_booleans_are_not_numbers() -> None:
    assert parse_field_type("int").coerce(True) is None
    assert parse_field_type("money(0,10)").coerce(False) is None


def test_json_schema_is_nullable_and_typed() -> None:
    schema = parse_field_type("enum:api|worker").json_schema
    assert schema == {"anyOf": [{"type": "string", "enum": ["api", "worker"]}, {"type": "null"}]}


@pytest.mark.parametrize(
    "spec",
    [
        "float",
        "money(5,1)",
        "money(a,b)",
        "pattern:([",
        "enum:",
        "text:0",
        "text:501",
        "text:x",
        "",
    ],
)
def test_invalid_specs_are_rejected(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_field_type(spec)
