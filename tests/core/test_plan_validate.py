"""Plan validator (F09, the MUST part). Spec: docs/features/F09-planner.md, validator passes."""

import pytest

from quarantix.core.plan import parse_plan
from quarantix.core.plan_validate import PlanLimits, validate_plan
from quarantix.core.registry import Registry


def _registry() -> Registry:
    registry = Registry()

    @registry.tool(kind="source")
    def read(status: str) -> list:
        """Read records."""
        return []

    @registry.tool(kind="sink", critical_args=("amount",))
    def pay(number: str, amount: float, memo: str = "") -> None:
        """Move money."""

    return registry


def _errors(steps: list, limits: PlanLimits | None = None) -> list[str]:
    plan = parse_plan({"steps": steps})
    return [str(e) for e in validate_plan(plan, _registry(), limits or PlanLimits())]


READ = {"op": "call", "id": "s1", "tool": "read", "args": {"status": "new"}, "out": "rows"}
DONE = {"op": "return", "id": "end", "value": "done"}


def test_a_valid_plan_has_no_errors() -> None:
    steps = [
        READ,
        {
            "op": "for_each", "id": "s2", "items": "$rows", "as": "r", "collect": "$line", "out": "lines",
            "body": [
                {"op": "extract", "id": "s3", "source": "$r.text", "fields": {"n": "pattern:^N-[0-9]+$"}, "out": "x"},
                {"op": "call", "id": "s4", "tool": "pay", "args": {"number": "$x.n", "amount": 5}},
                {"op": "format", "id": "s5", "template": "{n}", "values": {"n": "$x.n"}, "out": "line"},
            ],
        },
        {"op": "return", "id": "s6", "value": "$lines"},
    ]  # fmt: skip
    assert _errors(steps) == []


def test_pass_1_unknown_tools() -> None:
    errors = _errors([{"op": "call", "id": "s1", "tool": "teleport"}, DONE])
    assert errors == ["step s1: unknown tool 'teleport'"]


def test_pass_2_argument_names_and_required_arguments() -> None:
    errors = _errors(
        [
            {"op": "call", "id": "s1", "tool": "pay", "args": {"number": "N-1", "colour": "red"}},
            DONE,
        ]
    )
    assert "step s1: unknown argument 'colour' for pay" in errors
    assert "step s1: missing required argument 'amount' for pay" in errors


def test_pass_3_literal_types() -> None:
    errors = _errors(
        [
            {"op": "call", "id": "s1", "tool": "pay", "args": {"number": "N-1", "amount": "lots"}},
            DONE,
        ]
    )
    assert errors == ["step s1: argument 'amount' of pay must be number, got text"]


def test_pass_4_references_must_be_defined_earlier_in_scope() -> None:
    steps = [
        {"op": "call", "id": "s1", "tool": "pay", "args": {"number": "$later.n", "amount": 1}},
        {
            "op": "for_each", "id": "s2", "items": "$nothing", "as": "r",
            "body": [{"op": "format", "id": "s3", "template": "{v}", "values": {"v": "$r.id"}, "out": "inner"}],
        },
        {"op": "format", "id": "s4", "template": "{v}", "values": {"v": "$inner"}, "out": "x"},
        DONE,
    ]  # fmt: skip
    errors = _errors(steps)
    assert "step s1: reference $later.n is not defined before this step" in errors
    assert "step s2: reference $nothing is not defined before this step" in errors
    assert (
        "step s4: reference $inner is not defined before this step" in errors
    )  # loop scope does not leak


def test_values_defined_inside_an_if_are_visible_after_it() -> None:
    steps = [
        READ,
        {
            "op": "if", "id": "s2", "cond": {"ref": "$rows", "test": "truthy"},
            "then": [{"op": "format", "id": "s3", "template": "x", "values": {}, "out": "msg"}],
        },
        {"op": "return", "id": "s4", "value": "$msg"},
    ]  # fmt: skip
    assert _errors(steps) == []


def test_pass_5_extract_field_types() -> None:
    steps = [
        READ,
        {"op": "extract", "id": "s2", "source": "$rows", "fields": {"x": "money(9,1)"}, "out": "x"},
        DONE,
    ]
    assert [e for e in _errors(steps) if "field" in e] == [
        "step s2: field 'x' has an invalid type: money(9,1)"
    ]


def test_pass_6_size_limits() -> None:
    steps = [
        {"op": "format", "id": f"s{i}", "template": "x", "values": {}, "out": f"v{i}"}
        for i in range(5)
    ]
    errors = _errors([*steps, DONE], PlanLimits(max_steps=4, max_depth=3))
    assert errors == ["plan has 6 steps; the limit is 4"]
    nested = {"op": "if", "id": "a", "cond": {"ref": "$rows", "test": "truthy"}, "then": [
        {"op": "if", "id": "b", "cond": {"ref": "$rows", "test": "truthy"}, "then": [DONE]}]}  # fmt: skip
    assert _errors([READ, nested], PlanLimits(max_depth=1)) == [
        "plan nesting depth is 2; the limit is 1"
    ]


def test_pass_7_format_placeholders_must_match_values() -> None:
    steps = [
        READ,
        {
            "op": "format",
            "id": "s2",
            "template": "{a} {b}",
            "values": {"a": "$rows", "c": "$rows"},
            "out": "m",
        },
        DONE,
    ]
    errors = _errors(steps)
    assert errors == ["step s2: template placeholders ['a', 'b'] do not match values ['a', 'c']"]


def test_pass_8_a_return_step_is_required() -> None:
    assert _errors([READ]) == ["plan has no return step"]


def test_validation_stops_at_the_first_failing_pass() -> None:
    # Unknown tool (pass 1) and an undefined reference (pass 4): only pass 1 is reported.
    steps = [{"op": "call", "id": "s1", "tool": "teleport", "args": {"x": "$ghost"}}, DONE]
    assert _errors(steps) == ["step s1: unknown tool 'teleport'"]


@pytest.mark.perf
def test_validating_a_40_step_plan_is_fast() -> None:
    import time

    steps = [READ] + [
        {"op": "call", "id": f"p{i}", "tool": "pay", "args": {"number": "$rows", "amount": i}} for i in range(38)
    ] + [DONE]  # fmt: skip
    plan = parse_plan({"steps": steps})
    registry = _registry()
    start = time.perf_counter()
    assert validate_plan(plan, registry, PlanLimits()) == []
    elapsed = time.perf_counter() - start
    print(f"\nvalidate 40-step plan: {elapsed * 1e3:.2f} ms")
    assert elapsed < 2e-3
