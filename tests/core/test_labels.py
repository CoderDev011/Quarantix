"""F01 labels: the trust/sensitivity lattice. Spec: docs/features/F01-labels-provenance.md."""

import dataclasses
import time

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agentwall.core.labels import (
    BOTTOM,
    Confidentiality,
    Integrity,
    Label,
    Labeled,
    join_all,
    trusted,
    untrusted,
)

SOURCES = ["user", "planner", "system", "tool:list#1", "tool:get#2"]

labels = st.builds(
    Label,
    integrity=st.sampled_from(list(Integrity)),
    confidentiality=st.sampled_from(list(Confidentiality)),
    sources=st.frozensets(st.sampled_from(SOURCES), max_size=3),
)


@given(labels, labels)
def test_join_is_commutative(a: Label, b: Label) -> None:
    assert a.join(b) == b.join(a)


@given(labels, labels, labels)
def test_join_is_associative(a: Label, b: Label, c: Label) -> None:
    assert a.join(b).join(c) == a.join(b.join(c))


@given(labels)
def test_join_is_idempotent(a: Label) -> None:
    assert a.join(a) == a


@given(labels)
def test_bottom_is_the_identity(a: Label) -> None:
    assert a.join(BOTTOM) == a
    assert BOTTOM.join(a) == a


def test_one_untrusted_input_taints_the_result() -> None:
    joined = join_all([trusted("user"), untrusted("tool:list#1"), trusted("planner")])
    assert joined.integrity is Integrity.UNTRUSTED
    assert joined.sources == {"user", "tool:list#1", "planner"}


def test_join_takes_the_highest_confidentiality() -> None:
    low = trusted("user", Confidentiality.PUBLIC)
    high = trusted("system", Confidentiality.SECRET)
    assert low.join(high).confidentiality is Confidentiality.SECRET


def test_join_all_of_nothing_is_bottom() -> None:
    assert join_all([]) == BOTTOM


def test_helpers_default_to_internal_confidentiality() -> None:
    assert trusted("user").confidentiality is Confidentiality.INTERNAL
    assert untrusted("tool:list#1").integrity is Integrity.UNTRUSTED


def test_labels_are_immutable() -> None:
    label = trusted("user")
    with pytest.raises(dataclasses.FrozenInstanceError):
        label.integrity = Integrity.UNTRUSTED  # type: ignore[misc]


def _record() -> Labeled:
    """A trusted container whose `text` field is untrusted, like a list-tool result row."""
    return Labeled(
        value={
            "id": Labeled("T-1", trusted("system"), "n2"),
            "text": Labeled("hello", untrusted("tool:list#1", Confidentiality.PRIVATE), "n3"),
        },
        label=trusted("system"),
        node="n1",
    )


def test_untrusted_child_of_trusted_container_reads_untrusted() -> None:
    text = _record().field("text")
    assert text.label.integrity is Integrity.UNTRUSTED
    assert text.label.confidentiality is Confidentiality.PRIVATE
    assert text.node == "n3"


def test_trusted_child_of_untrusted_container_reads_untrusted() -> None:
    record = dataclasses.replace(_record(), label=untrusted("tool:list#1"))
    assert record.field("id").label.integrity is Integrity.UNTRUSTED


def test_missing_field_raises_key_error() -> None:
    with pytest.raises(KeyError):
        _record().field("nope")


def test_plain_strips_labels_recursively() -> None:
    nested = Labeled([_record(), Labeled(3, BOTTOM, "n4")], BOTTOM, "n5")
    assert nested.plain() == [{"id": "T-1", "text": "hello"}, 3]


@given(labels)
def test_wire_round_trip_is_identical(label: Label) -> None:
    assert Label.from_wire(label.to_wire()) == label


def test_wire_format_matches_contract() -> None:
    wire = untrusted("tool:list#1", Confidentiality.PRIVATE).join(trusted("user")).to_wire()
    assert wire == {
        "integrity": "untrusted",
        "confidentiality": "private",
        "sources": ["tool:list#1", "user"],
    }


@pytest.mark.perf
def test_join_in_a_loop_is_under_one_microsecond() -> None:
    """Budget: join under 1 µs typical (a running label absorbing repeated sources)."""
    inputs = [untrusted(f"tool:list#{i % 5}") for i in range(200_000)]
    running = BOTTOM
    start = time.perf_counter()
    for label in inputs:
        running = running.join(label)
    per_join = (time.perf_counter() - start) / len(inputs)
    print(f"\njoin (typical, dominated): {per_join * 1e9:.0f} ns")
    assert per_join < 1e-6
