"""Value tracer (F11): where did this argument come from, without a plan?

Every value an agent sees (the user's message, every tool result) is indexed by
its tokens with its label. When the agent later calls a tool, each argument's
tokens are looked up:

    no token found                         -> unknown (the session taint applies)
    some token only in untrusted sources   -> traced, untrusted
    tokens in both kinds, none only bad    -> ambiguous
    every token only in trusted sources    -> traced, trusted

A token returned by an *endorsed* tool (one that verified authority itself, e.g.
an ownership check) counts as trusted even if outsiders also wrote it: the
trusted record vouches for the value. Confidentiality is the highest among the
matched tokens. Tracing can only make a decision more precise than the session
taint; an unknown value always falls back to it.

The index is capped (default 5 MB, estimated); the oldest results are evicted
first and reported through `on_evict` so the caller can emit a limit event.
"""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from quarantix.core.labels import BOTTOM, Confidentiality, Integrity, Label

TraceEvidence = Literal["traced", "ambiguous", "unknown"]

MAX_INDEX_BYTES = 5_000_000
MAX_WHOLE = 200
MIN_WHOLE = 3
MAX_TOKENS_PER_VALUE = 20_000
_ENTRY_OVERHEAD = 72  # rough bytes per (token, entry) pair, for the cap
_ZERO_WIDTH = dict.fromkeys([*range(0x200B, 0x2010), 0x2060, 0xFEFF])
_SPACE = re.compile(r"\s+")
_URL = re.compile(r"https?://[^\s<>\"'`()\[\]{}|\\^]+")
_EMAIL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_IDENTIFIER = re.compile(r"[\w\-]{8,}")
_ACCOUNT = re.compile(r"\b[a-z]{2}\d{2}(?: ?[a-z0-9]{4}){3,7}\b")
_STOP = frozenset({"yes", "no", "ok", "okay", "true", "false", "none", "null", "n/a", "nan"})


def normalize(text: str) -> str:
    """NFKC, drop zero-width characters, case-fold, collapse whitespace."""
    if text.isascii():  # fast path: NFKC and zero-width removal are no-ops on ASCII
        return " ".join(text.lower().split())
    text = unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)
    return " ".join(text.casefold().split())


def _canonical_number(raw: str) -> str:
    if raw.isdigit() and raw[0] != "0":
        return raw  # fast path: a plain whole number is already canonical
    number = raw.replace(",", "")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return number.lstrip("0") or "0"


def _significant(number: str) -> int:
    return len(number.replace(".", "").lstrip("0"))


def tokens(value: Any) -> set[str]:
    """The tokens of a scalar value (see the module docstring)."""
    if value is None or isinstance(value, bool):
        return set()
    if isinstance(value, int | float):
        number = _canonical_number(repr(float(value)) if isinstance(value, float) else str(value))
        return {number} if _significant(number) >= 2 else set()
    text = normalize(str(value))
    if not text:
        return set()
    out: set[str] = set()
    whole = _canonical_number(text) if _NUMBER.fullmatch(text) else text
    if (MIN_WHOLE <= len(whole) <= MAX_WHOLE and whole not in _STOP) or (
        _NUMBER.fullmatch(text) and _significant(whole) >= 2
    ):
        out.add(whole)
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(".,;:!?")
        out.add(url)
        host = url.split("://", 1)[1].split("/", 1)[0].split("?", 1)[0].rsplit("@", 1)[-1]
        if host:
            out.add(host)
            out.add(host.split(":", 1)[0])
    if "@" in text:
        out.update(_EMAIL.findall(text))
    for raw in set(_NUMBER.findall(text)):
        number = _canonical_number(raw)
        if len(number) >= 3 and _significant(number) >= 3:
            out.add(number)
    out.update(_IDENTIFIER.findall(text))
    out.update(m.group(0).replace(" ", "") for m in _ACCOUNT.finditer(text))
    out.discard("")
    if len(out) > MAX_TOKENS_PER_VALUE:  # bound the work per value
        out = set(sorted(out, key=len, reverse=True)[:MAX_TOKENS_PER_VALUE])
    return out


@dataclass(frozen=True, slots=True)
class _Entry:
    integrity: Integrity
    confidentiality: Confidentiality
    source: str
    endorsed: bool
    node: str | None


@dataclass(frozen=True, slots=True)
class Trace:
    evidence: TraceEvidence
    integrity: Integrity
    confidentiality: Confidentiality
    sources: frozenset[str]
    matched_tokens: frozenset[str]
    nodes: tuple[str, ...]

    @property
    def label(self) -> Label:
        return Label(self.integrity, self.confidentiality, self.sources)


UNKNOWN = Trace("unknown", Integrity.TRUSTED, Confidentiality.PUBLIC, frozenset(), frozenset(), ())


class ValueTracer:
    def __init__(
        self,
        *,
        max_bytes: int = MAX_INDEX_BYTES,
        on_evict: Callable[[int], None] | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.on_evict = on_evict
        self._index: dict[str, dict[int, _Entry]] = {}
        self._results: deque[tuple[int, tuple[str, ...], int]] = deque()  # id, tokens, bytes
        self._next = 0
        self.size_bytes = 0

    # ---------------------------------------------------------------- indexing

    def index_user(self, text: str, node: str | None = None) -> None:
        self.index(
            text, Label(Integrity.TRUSTED, Confidentiality.INTERNAL, frozenset({"user"})), node=node
        )

    def index(
        self,
        value: Any,
        label: Label,
        *,
        endorsed: bool = False,
        node: str | None = None,
        field_labels: Mapping[str, Label] | None = None,
    ) -> None:
        """Index a value (scalar, mapping or list) with its label.

        For mappings, `field_labels` overrides the label of named fields (the tool
        spec's per-field labels), applied to every record in a list.
        """
        source = next(iter(sorted(label.sources)), "unknown")
        result_id = self._next
        self._next += 1
        added: list[str] = []
        for leaf, leaf_label in _leaves(value, label, field_labels or {}):
            entry = _Entry(
                leaf_label.integrity,
                leaf_label.confidentiality,
                next(iter(sorted(leaf_label.sources)), source),
                endorsed and leaf_label.integrity is Integrity.TRUSTED,
                node,
            )
            index = self._index
            for token in tokens(leaf):
                bucket = index.get(token)
                if bucket is None:
                    index[token] = {result_id: entry}
                    added.append(token)
                elif result_id in bucket:  # the same token twice in one result: keep the weaker
                    bucket[result_id] = _weaker(bucket[result_id], entry)
                else:
                    bucket[result_id] = entry
                    added.append(token)
        cost = sum(len(t) + _ENTRY_OVERHEAD for t in added)
        self._results.append((result_id, tuple(added), cost))
        self.size_bytes += cost
        self._evict()

    def _evict(self) -> None:
        evicted = 0
        while self.size_bytes > self.max_bytes and len(self._results) > 1:
            result_id, added, cost = self._results.popleft()
            for token in added:
                bucket = self._index.get(token)
                if bucket is not None:
                    bucket.pop(result_id, None)
                    if not bucket:
                        del self._index[token]
            self.size_bytes -= cost
            evicted += 1
        if evicted and self.on_evict is not None:
            self.on_evict(evicted)

    # ---------------------------------------------------------------- tracing

    def trace(self, value: Any) -> Trace:
        if isinstance(value, Mapping | list | tuple):
            return self._combine(self.trace(v) for v in _scalars(value))
        index = self._index
        trusted = Integrity.TRUSTED
        matched: list[str] = []
        confidentiality = Confidentiality.PUBLIC
        sources: set[str] = set()
        bad_sources: set[str] = set()
        nodes: dict[str, None] = {}
        any_only_bad = any_mixed = False
        for token in tokens(value):  # one pass, no intermediate lists (hot path)
            bucket = index.get(token)
            if bucket is None:
                continue
            matched.append(token)
            good = bad = endorsed = False
            for e in bucket.values():
                if e.confidentiality > confidentiality:
                    confidentiality = e.confidentiality
                if e.integrity is trusted:
                    good = True
                    endorsed = endorsed or e.endorsed
                else:
                    bad = True
                sources.add(e.source)
                if e.node and len(nodes) < 10:
                    nodes[e.node] = None
            if endorsed or not bad:
                continue  # an endorsed trusted record vouches for this token
            if good:
                any_mixed = True
            else:
                any_only_bad = True
                bad_sources.update(e.source for e in bucket.values())
        if not matched:
            return UNKNOWN
        found = frozenset(matched)
        node_ids = tuple(nodes)
        if any_only_bad:
            return Trace(
                "traced",
                Integrity.UNTRUSTED,
                confidentiality,
                frozenset(bad_sources),
                found,
                node_ids,
            )
        if any_mixed:
            return Trace(
                "ambiguous",
                Integrity.UNTRUSTED,
                confidentiality,
                frozenset(sources),
                found,
                node_ids,
            )
        return Trace("traced", trusted, confidentiality, frozenset(sources), found, node_ids)

    @staticmethod
    def _combine(traces: Iterable[Trace]) -> Trace:
        """A container argument: the worst of its parts."""
        rank = {"unknown": 0, "traced": 1, "ambiguous": 2}
        result = UNKNOWN
        for t in traces:
            if t.evidence == "unknown":
                continue
            if result.evidence == "unknown":
                result = t
                continue
            integrity = max(result.integrity, t.integrity)
            evidence: TraceEvidence = "traced"
            if integrity is Integrity.UNTRUSTED:
                bad = [x for x in (result, t) if x.integrity is Integrity.UNTRUSTED]
                evidence = "traced" if any(x.evidence == "traced" for x in bad) else "ambiguous"
            elif rank[t.evidence] > rank[result.evidence]:
                evidence = t.evidence
            result = Trace(
                evidence,
                integrity,
                max(result.confidentiality, t.confidentiality),
                result.sources | t.sources,
                result.matched_tokens | t.matched_tokens,
                tuple(dict.fromkeys((*result.nodes, *t.nodes)))[:10],
            )
        return result


def _weaker(a: _Entry, b: _Entry) -> _Entry:
    if (b.integrity, b.confidentiality) > (a.integrity, a.confidentiality):
        return b
    return a


def _scalars(value: Any) -> Iterable[Any]:
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _scalars(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _scalars(item)
    else:
        yield value


def _leaves(
    value: Any, label: Label, field_labels: Mapping[str, Label]
) -> Iterable[tuple[Any, Label]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            override = field_labels.get(str(key))
            yield from _leaves(item, override if override is not None else label, {})
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _leaves(item, label, field_labels)
    else:
        yield value, label


__all__ = ["BOTTOM", "UNKNOWN", "Trace", "ValueTracer", "normalize", "tokens"]
