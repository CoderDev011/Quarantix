"""Plan language parsing. Spec: docs/contracts.md section 4 (structure only; F09 validates meaning)."""

import pytest

from quarantix.core.plan import (
    Call,
    Extract,
    ForEach,
    Format,
    If,
    PlanError,
    Ref,
    Return,
    parse_plan,
)

ALL_STEPS = {
    "schema_version": 1,
    "steps": [
        {"op": "call", "id": "s1", "tool": "list", "args": {"status": "new"}, "out": "rows"},
        {
            "op": "for_each",
            "id": "s2",
            "items": "$rows",
            "as": "row",
            "collect": "$line",
            "out": "lines",
            "body": [
                {
                    "op": "extract",
                    "id": "s3",
                    "source": "$row.text",
                    "fields": {"wants": "bool"},
                    "out": "x",
                },
                {
                    "op": "if",
                    "id": "s4",
                    "cond": {"ref": "$x.wants", "test": "truthy"},
                    "then": [
                        {
                            "op": "format",
                            "id": "s5",
                            "template": "Row {id}",
                            "values": {"id": "$row.id"},
                            "out": "line",
                        }
                    ],
                    "else": [],
                },
            ],
        },
        {"op": "return", "id": "s6", "value": "$lines[0]"},
    ],
}


def test_every_step_type_parses() -> None:
    plan = parse_plan(ALL_STEPS)
    call, loop, done = plan.steps
    assert isinstance(call, Call) and call.args == {"status": "new"}
    assert isinstance(loop, ForEach) and loop.as_ == "row" and loop.collect == Ref("line", ())
    extract, branch = loop.body
    assert isinstance(extract, Extract) and extract.source == Ref("row", ("text",))
    assert isinstance(branch, If) and branch.cond.test == "truthy"
    assert isinstance(branch.then[0], Format)
    assert isinstance(done, Return) and done.value == Ref("lines", (0,))


def test_strings_starting_with_dollar_are_references() -> None:
    plan = parse_plan(
        {"steps": [{"op": "call", "id": "s1", "tool": "t", "args": {"a": "$x.y[2]", "b": "lit"}}]}
    )
    call = plan.steps[0]
    assert isinstance(call, Call)
    assert call.args["a"] == Ref("x", ("y", 2))
    assert call.args["b"] == "lit"


@pytest.mark.parametrize(
    ("step", "fragment"),
    [
        ({"op": "eval", "id": "s1"}, "op"),
        ({"op": "call", "id": "s1"}, "tool"),
        ({"op": "call", "id": "s1", "tool": "t", "args": {"a": "$Bad-Ref"}}, "reference"),
        ({"op": "call", "id": "s1", "tool": "t", "surprise": 1}, "surprise"),
        ({"op": "if", "id": "s1", "cond": {"ref": "$x", "test": "maybe"}, "then": []}, "test"),
        ({"op": "return", "id": ""}, "id"),
    ],
)
def test_malformed_steps_are_rejected(step: dict, fragment: str) -> None:
    with pytest.raises(PlanError) as error:
        parse_plan({"steps": [step]})
    assert fragment in str(error.value)


def test_duplicate_step_ids_are_rejected() -> None:
    steps = [{"op": "return", "id": "s1", "value": "a"}, {"op": "return", "id": "s1", "value": "b"}]
    with pytest.raises(PlanError, match="duplicate"):
        parse_plan({"steps": steps})


def test_unsupported_schema_version_is_rejected() -> None:
    with pytest.raises(PlanError, match="schema_version"):
        parse_plan({"schema_version": 2, "steps": []})


def test_needs_approval_plans_parse_without_steps() -> None:
    plan = parse_plan({"steps": [], "needs_approval": True, "reason": "asks to obey a document"})
    assert plan.needs_approval
    assert plan.reason == "asks to obey a document"
