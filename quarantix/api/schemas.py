"""Response and request models for the HTTP API (F13).

They mirror docs/contracts.md (sections 1, 6, 7 and 8). They exist so OpenAPI
describes every console response; the dashboard's TypeScript types are generated
from that (scripts/gen_types.sh), never written by hand.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class LabelOut(_Out):
    integrity: Literal["trusted", "untrusted"]
    confidentiality: Literal["public", "internal", "private", "secret"]
    sources: list[str]


class ArgPreviewOut(_Out):
    preview: str
    label: LabelOut | None = None
    evidence: str | None = None
    sha256: str | None = None
    redacted: bool = False


class PathNodeOut(_Out):
    id: str
    kind: str
    title: str
    label: LabelOut


class PathEdgeOut(_Out):
    source: str
    target: str


class ProvenanceOut(_Out):
    nodes: list[PathNodeOut]
    edges: list[PathEdgeOut]


class DecisionOut(_Out):
    kind: Literal["allow", "ask", "block"]
    rule: str
    reason: str
    offending_arg: str | None = None
    matched: list[str] = []
    provenance: ProvenanceOut | None = None
    policy_version: str
    enforced: bool = True


class EventOut(_Out):
    schema_version: int
    seq: int | None = None
    event_id: str
    run_id: str
    agent: str
    mode: Literal["full", "guard"]
    kind: str
    time: str
    tool: str | None = None
    args: dict[str, ArgPreviewOut] | None = None
    context: LabelOut | None = None
    decision: DecisionOut | None = None
    outcome: Literal["executed", "blocked", "skipped", "error"] | None = None
    latency_ms: float | None = None
    data: dict[str, Any] = {}


class EventsPage(_Out):
    events: list[EventOut]


class AgentOut(_Out):
    name: str
    online: bool
    mode: Literal["enforce", "monitor", "off"]
    policy_version: str
    sdk_version: str | None = None


class AgentsPage(_Out):
    agents: list[AgentOut]


class ApprovalOut(_Out):
    id: str
    run_id: str
    agent: str
    tool: str
    rule: str
    reason: str
    args: dict[str, ArgPreviewOut]
    age_s: float


class ApprovalsPage(_Out):
    approvals: list[ApprovalOut]


class SessionIn(BaseModel):
    token: str
