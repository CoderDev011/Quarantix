"""Labels: who could have written a value, and who may see it (F01, contracts section 1-2).

A label is immutable. `join` combines two labels by taking the higher integrity
(untrusted wins), the higher confidentiality, and the union of sources. Join is
commutative, associative and idempotent, with BOTTOM as its identity.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import IntEnum
from functools import reduce
from typing import Any


class Integrity(IntEnum):
    TRUSTED = 0
    UNTRUSTED = 1


class Confidentiality(IntEnum):
    PUBLIC = 0
    INTERNAL = 1
    PRIVATE = 2
    SECRET = 3


@dataclass(frozen=True, slots=True)
class Label:
    integrity: Integrity
    confidentiality: Confidentiality
    sources: frozenset[str] = frozenset()

    def join(self, other: Label) -> Label:
        # Fast paths: when one label already covers the other, reuse it instead of
        # allocating. This is the common case for a running label inside a loop.
        if other is self or self._covers(other):
            return self
        if other._covers(self):
            return other
        return Label(
            max(self.integrity, other.integrity),
            max(self.confidentiality, other.confidentiality),
            self.sources | other.sources,
        )

    def _covers(self, other: Label) -> bool:
        return (
            self.integrity >= other.integrity
            and self.confidentiality >= other.confidentiality
            and other.sources <= self.sources
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "integrity": self.integrity.name.lower(),
            "confidentiality": self.confidentiality.name.lower(),
            "sources": sorted(self.sources),
        }

    @classmethod
    def from_wire(cls, wire: Mapping[str, Any]) -> Label:
        try:
            return cls(
                Integrity[str(wire["integrity"]).upper()],
                Confidentiality[str(wire["confidentiality"]).upper()],
                frozenset(wire.get("sources", ())),
            )
        except KeyError as exc:
            raise ValueError(f"invalid label on the wire: {wire!r}") from exc


BOTTOM = Label(Integrity.TRUSTED, Confidentiality.PUBLIC, frozenset())


def trusted(source: str, confidentiality: Confidentiality = Confidentiality.INTERNAL) -> Label:
    return Label(Integrity.TRUSTED, confidentiality, frozenset({source}))


def untrusted(source: str, confidentiality: Confidentiality = Confidentiality.INTERNAL) -> Label:
    return Label(Integrity.UNTRUSTED, confidentiality, frozenset({source}))


def join_all(labels: Iterable[Label]) -> Label:
    return reduce(Label.join, labels, BOTTOM)


@dataclass(frozen=True, slots=True)
class Labeled:
    """A value with its label and provenance node.

    `value` is a scalar, a mapping of field name to Labeled, or a list of Labeled.
    For containers, `label` is the label of the structure itself.
    """

    value: Any
    label: Label
    node: str

    def field(self, name: str) -> Labeled:
        """Read a child field. Its label is joined with the container's label."""
        child: Labeled = self.value[name]
        return Labeled(child.value, child.label.join(self.label), child.node)

    def plain(self) -> Any:
        """The value with every label removed, recursively (what real tools receive)."""
        return _plain(self.value)


def _plain(value: Any) -> Any:
    if isinstance(value, Labeled):
        value = value.value
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return value
