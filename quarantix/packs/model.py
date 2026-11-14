"""Domain-pack records (contracts section 10). Immutable, built once by the loader."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from quarantix.core.labels import Confidentiality
from quarantix.core.plan import Plan
from quarantix.core.registry import Registry, ToolSpec
from quarantix.engine.policy import Pack

Authored = Literal["outsider", "system"]
Behavior = Literal[
    "list_records",
    "get_record",
    "read_secret",
    "fetch_page",
    "ledger_write",
    "post_internal",
    "send_external",
    "run_command",
]
BEHAVIOR_KIND: Mapping[str, str] = {
    "list_records": "source",
    "get_record": "source",
    "read_secret": "source",
    "fetch_page": "source",
    "ledger_write": "sink",
    "post_internal": "sink",
    "send_external": "sink",
    "run_command": "sink",
}
GoalKind = Literal[
    "money_to_attacker", "secret_exfiltrated", "link_planted", "data_to_public", "forbidden_action"
]
GOAL_KINDS = frozenset(
    {
        "money_to_attacker",
        "secret_exfiltrated",
        "link_planted",
        "data_to_public",
        "forbidden_action",
    }
)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    type: str
    confidentiality: Confidentiality
    text: bool = False


@dataclass(frozen=True, slots=True)
class StoreSpec:
    name: str
    id_field: str
    authored_by: Authored
    fields: Mapping[str, FieldSpec]


@dataclass(frozen=True, slots=True)
class ToolManifest:
    """A manifest tool: its decision metadata (`spec`, no implementation) and its behavior."""

    spec: ToolSpec
    behavior: Behavior
    config: Mapping[str, Any]
    params: tuple[str, ...]
    required: frozenset[str]


@dataclass(frozen=True, slots=True)
class AttackerMarkers:
    host: str  # e.g. attacker:9000, as written in payloads
    aliases: tuple[str, ...]  # other host:port spellings of the same local attacker server
    account: str
    email: str
    values: tuple[float, ...]

    @property
    def hosts(self) -> tuple[str, ...]:
        return (self.host, *self.aliases)

    @property
    def url(self) -> str:
        return f"http://{self.host}"

    def slots(self) -> dict[str, str]:
        value = self.values[0] if self.values else 4999.0
        return {
            "attacker_host": self.host,
            "attacker_url": self.url,
            "attacker_account": self.account,
            "attacker_email": self.email,
            "attacker_value": f"{value:.2f}",
        }


@dataclass(frozen=True, slots=True)
class Goal:
    id: str
    kind: GoalKind
    title: str
    params: Mapping[str, Any]
    points: float = 1.0


@dataclass(frozen=True, slots=True)
class PlantTarget:
    store: str
    field: str
    record: str  # a record id, or "new"
    new_id: str | None = None
    defaults: Mapping[str, Any] = dataclasses.field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Task:
    id: str
    request: str
    plan: str
    plant: PlantTarget


@dataclass(frozen=True, slots=True)
class Plant:
    store: str
    record: str  # a record id, or "new"
    field: str
    payload: str


@dataclass(frozen=True, slots=True)
class Attack:
    id: str
    domain: str
    technique: str
    task_id: str
    goal_id: str
    plant: Plant
    template_id: str | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class BenignTask:
    id: str
    domain: str
    task_id: str
    expected: tuple[Mapping[str, Any], ...]
    plant: Plant | None = None
    notes: str = ""


@dataclass(frozen=True, slots=True)
class Domain:
    name: str
    title: str
    description: str
    agent: str
    system_prompt: str
    org_domains: frozenset[str]
    attacker: AttackerMarkers
    stores: Mapping[str, StoreSpec]
    tools: Mapping[str, ToolManifest]
    registry: Registry  # decision metadata only; worlds bind the implementations
    ledgers: frozenset[str]
    goals: Mapping[str, Goal]
    tasks: Mapping[str, Task]
    plans: Mapping[str, Plan]
    policy_text: str
    policy: Pack
    day_one_text: str
    attacks: tuple[Attack, ...]
    benign: tuple[BenignTask, ...]
    capabilities: frozenset[str]
    seed: Any  # world.Seed (kept untyped here to avoid an import cycle)
    allowed_link_hosts: frozenset[str]

    def world(self, link: Any = None) -> Any:
        """A fresh world over this domain's immutable seed (cheap: copy-on-write)."""
        from quarantix.packs.world import World

        return World(self, link=link)
