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


# ---------------------------------------------------------------- arena (F15, contracts section 13)


class DefenderOut(_Out):
    outcome: Literal["breached", "blocked", "neutralized", "needs_approval", "error"]
    rule: str | None = None
    attacker_hits: int = 0
    latency_ms: float = 0.0
    evaluation: Literal["shadow", "enforced"] = "enforced"
    step: int | None = None


class DefendersOut(_Out):
    naive: DefenderOut | None = None
    guard: DefenderOut | None = None
    full: DefenderOut | None = None


class AttemptOut(_Out):
    attempt_id: str
    time: str
    nickname: str
    domain: str
    goal_id: str
    goal_title: str
    technique_tags: list[str]
    status: Literal["queued", "running", "done"]
    queue_position: int = 0
    defenders: DefendersOut
    points: float = 0.0
    seen_before: bool = False
    pending_rerun: bool = False
    source: Literal["human", "red_agent"] = "human"


class AdminAttemptOut(AttemptOut):
    payload: str
    player_id: str
    hidden: bool = False


class AdminAttemptsPage(_Out):
    attempts: list[AdminAttemptOut]


class GoalOut(_Out):
    domain: str
    domain_title: str
    goal_id: str
    kind: str
    title: str
    points: float


class GoalsPage(_Out):
    goals: list[GoalOut]


class LeaderRowOut(_Out):
    rank: int
    nickname: str
    points: float
    attempts: int
    breaches: int


class LeaderboardPage(_Out):
    leaderboard: list[LeaderRowOut]


class BreachCountsOut(_Out):
    naive: int = 0
    guard: int = 0
    full: int = 0


class ArenaStatsOut(_Out):
    attempts: int
    attacks_per_minute: int
    breaches: BreachCountsOut
    breaches_found: int
    breaches_patched: int
    baseline_model: str | None = None
    economy: bool = False
    paused: bool = False
    queue_depth: int = 0
    public_url: str = ""


class ResetOut(_Out):
    restored: list[str]
    removed: list[str]
    cleared_leaderboard: bool
    seconds: float


# ---------------------------------------------------------------- Autopilot (F18, section 14)


class CandidateRuleOut(_Out):
    template: str
    parameters: dict[str, Any]


class RateOut(_Out):
    k: int
    n: int
    rate: float | None = None
    ci95: list[float]


class ProofSideOut(_Out):
    asr: RateOut
    tsr: RateOut
    false_block_rate: RateOut
    approval_rate: RateOut


class ChangedCaseOut(_Out):
    case_id: str
    before: str
    after: str
    rule: str | None = None


class TriggerProofOut(_Out):
    attempt_id: str
    before: str
    after: str
    rule: str | None = None
    stopped: bool


class ProofOut(_Out):
    verdict: Literal["pass", "fail"]
    reasons: list[str] = []
    mode: str | None = None
    trace_sources: list[str] = []
    cases: int = 0
    before: ProofSideOut | None = None
    after: ProofSideOut | None = None
    trigger: TriggerProofOut | None = None
    trigger_stopped: bool | None = None
    decisions: dict[str, Any] = {}
    changed_cases: list[ChangedCaseOut] = []
    seconds: float = 0.0


class ProposalOut(_Out):
    proposal_id: str
    created: str
    trigger: Literal["arena_breach", "monitor_findings", "manual", "red_agent_breach"]
    domain: str
    agent: str
    evidence_ids: list[str]
    facts: dict[str, Any]
    candidate_rules: list[CandidateRuleOut]
    tighten_only: bool
    rationale: str
    draft_source: str
    draft_notes: list[str] = []
    pack_name: str
    pack_yaml: str
    proof: ProofOut | None = None
    status: Literal[
        "drafted", "proving", "proved_pass", "proved_fail", "enabled", "rejected", "rolled_back"
    ]
    enabled_by: str | None = None
    seconds_to_patch: float | None = None
    enabled_version: str | None = None
    previous_version: str | None = None


class ProposalsPage(_Out):
    proposals: list[ProposalOut]


class AutopilotSettingsOut(_Out):
    autonomous: bool


# ---------------------------------------------------------------- proof suite (F22, section 12)


class ProofModeOut(_Out):
    outcome: str
    rule: str | None = None
    expected: list[str] = []
    expected_rule: str | None = None
    passed: bool | None = None
    source: str | None = None
    why: str | None = None


class ScenarioResultOut(_Out):
    scenario_id: str
    title: str
    category: str
    verdict: Literal["pass", "fail", "partial"]
    modes: dict[str, ProofModeOut]
    seconds: float


class ProofReportOut(_Out):
    scenarios: list[ScenarioResultOut]
    passed: int
    partial: int
    failed: int
    total: int


# ---------------------------------------------------------------- domain generator (F19)


class ReviewItemOut(_Out):
    subject: str
    decision: str
    reason: str
    changed: bool


class DraftGoalOut(_Out):
    goal_id: str
    kind: str
    title: str


class DraftOut(_Out):
    draft_id: str
    description: str
    name: str
    status: Literal["validated", "failed", "confirmed"]
    guard_only: bool
    review: list[ReviewItemOut]
    changed_by_hardening: int
    errors: list[str] = []
    goals: list[DraftGoalOut] = []
    tools: list[str] = []
    agent: str | None = None


class AutopilotProgressOut(_Out):
    proposal_id: str
    status: str
    domain: str
    verdict: str | None = None
    seconds_to_patch: float | None = None
    templates: list[str] = []
    attempt_ids: list[str] = []
    cases: int | None = None
