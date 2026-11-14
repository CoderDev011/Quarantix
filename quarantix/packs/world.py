"""A domain world: stores and ledgers over an immutable seed (F03).

The seed is loaded once and never changes. A world keeps copy-on-write overlays
(planted or created records) and its own ledgers, so `clone()` costs a few
dictionary copies, not a deep copy of the data. Records handed out are shallow
copies; overlay records are replaced, never mutated, so sharing them is safe.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from quarantix.core.registry import Registry
from quarantix.packs.attacker import AttackerHit, AttackerLink

if TYPE_CHECKING:
    from quarantix.packs.model import Domain

MAX_LEDGER_ROWS = 1000


class WorldError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Seed:
    order: Mapping[str, tuple[str, ...]]  # store -> record ids in seed order
    records: Mapping[str, Mapping[str, Mapping[str, Any]]]  # store -> id -> record

    @classmethod
    def build(
        cls, stores: Mapping[str, list[dict[str, Any]]], id_fields: Mapping[str, str]
    ) -> Seed:
        order: dict[str, tuple[str, ...]] = {}
        records: dict[str, Mapping[str, Mapping[str, Any]]] = {}
        for store, rows in stores.items():
            by_id = {str(row[id_fields[store]]): MappingProxyType(dict(row)) for row in rows}
            order[store] = tuple(by_id)
            records[store] = MappingProxyType(by_id)
        return cls(MappingProxyType(order), MappingProxyType(records))


class World:
    __slots__ = ("_added", "_overlay", "_registry", "domain", "ledgers", "link")

    def __init__(self, domain: Domain, *, link: AttackerLink | None = None) -> None:
        self.domain = domain
        self.link = link if link is not None else default_link(domain)
        self._overlay: dict[str, dict[str, Mapping[str, Any]]] = {}
        self._added: dict[str, list[str]] = {}
        self.ledgers: dict[str, list[dict[str, Any]]] = {name: [] for name in domain.ledgers}
        self._registry: Registry | None = None

    # ---------------------------------------------------------------- copies

    def clone(self) -> World:
        """An isolated copy: same seed, copied overlays and ledgers, an empty attacker log."""
        twin = World.__new__(World)
        twin.domain = self.domain
        twin.link = self.link.fresh()
        twin._overlay = {store: dict(records) for store, records in self._overlay.items()}
        twin._added = {store: list(ids) for store, ids in self._added.items()}
        twin.ledgers = {name: list(rows) for name, rows in self.ledgers.items()}
        twin._registry = None
        return twin

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """The ledgers as plain data, for checks and reports."""
        return {name: [dict(row) for row in rows] for name, rows in self.ledgers.items()}

    @property
    def attacker_hits(self) -> list[AttackerHit]:
        return list(self.link.hits)

    @property
    def registry(self) -> Registry:
        """The domain's tools bound to this world (built on first use)."""
        if self._registry is None:
            from quarantix.packs.executor import bind_registry

            self._registry = bind_registry(self)
        return self._registry

    # ---------------------------------------------------------------- reads

    def _seed_store(self, store: str) -> Mapping[str, Mapping[str, Any]]:
        try:
            return self.domain.seed.records[store]
        except KeyError:
            raise WorldError(f"unknown store {store!r}") from None

    def ids(self, store: str) -> list[str]:
        self._seed_store(store)
        return [*self.domain.seed.order[store], *self._added.get(store, ())]

    def get(self, store: str, record_id: str) -> dict[str, Any] | None:
        overlay = self._overlay.get(store)
        if overlay is not None and record_id in overlay:
            return dict(overlay[record_id])
        record = self._seed_store(store).get(record_id)
        return None if record is None else dict(record)

    def records(self, store: str) -> list[dict[str, Any]]:
        seed = self._seed_store(store)
        overlay = self._overlay.get(store, {})
        out: list[dict[str, Any]] = []
        for record_id in self.ids(store):
            record = overlay.get(record_id) or seed.get(record_id)
            if record is not None:
                out.append(dict(record))
        return out

    def lookup(self, store: str, record_id: str) -> Mapping[str, Any] | None:
        """Record lookup for audience rules (registry RecordLookup)."""
        try:
            return self.get(store, record_id)
        except WorldError:
            return None

    # ---------------------------------------------------------------- writes

    def plant(
        self,
        store: str,
        record: str,
        field: str,
        payload: str,
        *,
        new_id: str | None = None,
        defaults: Mapping[str, Any] | None = None,
    ) -> str:
        """Append `payload` to a record's field, or create a new record. Returns its id.

        The payload is stored as plain text, never parsed. Planting into a record id
        that does not exist creates it.
        """
        spec = self.domain.stores.get(store)
        if spec is None:
            raise WorldError(f"unknown store {store!r}")
        if field not in spec.fields:
            raise WorldError(f"store {store!r} has no field {field!r}")
        payload = str(payload)
        existing = None if record == "new" else self.get(store, record)
        if existing is not None:
            current = existing.get(field)
            joined = f"{current}\n{payload}" if current not in (None, "") else payload
            self._overlay.setdefault(store, {})[record] = MappingProxyType(
                {**existing, field: joined}
            )
            return record

        record_id = self._new_id(store, record if record != "new" else (new_id or f"{store}-new"))
        row = {**dict(defaults or {}), spec.id_field: record_id, field: payload}
        self._overlay.setdefault(store, {})[record_id] = MappingProxyType(row)
        self._added.setdefault(store, []).append(record_id)
        return record_id

    def _new_id(self, store: str, wanted: str) -> str:
        taken = set(self.ids(store))
        if wanted not in taken:
            return wanted
        n = 2
        while f"{wanted}-{n}" in taken:
            n += 1
        return f"{wanted}-{n}"

    def append(self, ledger: str, row: Mapping[str, Any]) -> None:
        rows = self.ledgers.get(ledger)
        if rows is None:
            raise WorldError(f"unknown ledger {ledger!r}")
        if len(rows) >= MAX_LEDGER_ROWS:
            raise WorldError(f"ledger {ledger!r} is full ({MAX_LEDGER_ROWS} rows)")
        rows.append(dict(row))


def default_link(domain: Domain) -> AttackerLink:
    """A recording-only link (no delivery) for the domain's attacker markers."""
    markers = domain.attacker
    email_domain = markers.email.rsplit("@", 1)[-1] if "@" in markers.email else ""
    return AttackerLink(markers.hosts, email_domains=(email_domain,) if email_domain else ())
