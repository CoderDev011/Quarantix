"""Real-World Proof Suite (F22, contracts section 12).

Each scenario names its source (an incident in docs/incidents.md, or the
real-world pattern it is an analog of), a stimulus (an attack or benign case of a
domain pack), and the expected outcome per mode. Baseline and guard replay the
case's recorded trace (free, deterministic); full runs the pinned plan when a
reader is available and is reported as "skipped" otherwise, never as a pass.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quarantix.arena.defenders import Brains
from quarantix.arena.suite import Case, Trace, _NoModel, cases_for, replay, run_live
from quarantix.autopilot.templates import Candidate, build_pack
from quarantix.engine.interpreter import Reader
from quarantix.engine.policy import Pack, PolicyBundle, compile_pack
from quarantix.packs.model import Domain

CATEGORIES = frozenset({"incident_replay", "everyday_attack", "legit_use", "operations"})
MODES = frozenset({"baseline", "guard", "full", "mcp"})
_KEYS = frozenset(
    {
        "id",
        "title",
        "category",
        "source",
        "domain",
        "modes",
        "setup",
        "stimulus",
        "expected",
        "pass_line",
        "evidence",
        "priority",
    }
)


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Scenario:
    id: str
    title: str
    category: str
    source: Mapping[str, Any]
    domain: str
    modes: tuple[str, ...]
    stimulus: str
    expected: Mapping[str, Mapping[str, Any]]
    setup: tuple[Mapping[str, Any], ...] = ()
    pass_line: str = ""
    evidence: tuple[str, ...] = ()
    priority: str = "MUST"


@dataclass(slots=True)
class ScenarioResult:
    scenario_id: str
    title: str
    category: str
    verdict: str  # pass | fail | partial (some modes skipped)
    modes: dict[str, dict[str, Any]] = field(default_factory=dict)
    seconds: float = 0.0

    def to_wire(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "title": self.title,
            "category": self.category,
            "verdict": self.verdict,
            "modes": self.modes,
            "seconds": round(self.seconds, 3),
        }


def load_scenarios(root: str | Path, incidents: str | Path | None = None) -> list[Scenario]:
    """Read and check every scenario. Incident replays must cite an incident id in incidents.md."""
    cited = Path(incidents).read_text(encoding="utf-8") if incidents else None
    scenarios = []
    for path in sorted(Path(root).glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) - _KEYS:
            raise ScenarioError(f"{path.name}: unknown or missing keys")
        if data.get("category") not in CATEGORIES:
            raise ScenarioError(f"{path.name}: invalid category")
        modes = tuple(data.get("modes") or ())
        if not modes or set(modes) - MODES:
            raise ScenarioError(f"{path.name}: invalid modes")
        source = data.get("source") or {}
        if data["category"] == "incident_replay":
            incident = str(source.get("incident", ""))
            if cited is not None and f"## {incident}." not in cited:
                raise ScenarioError(
                    f"{path.name}: incident {incident!r} is not in docs/incidents.md"
                )
        expected = data.get("expected") or {}
        if set(expected) != set(modes):
            raise ScenarioError(f"{path.name}: expected outcomes must cover exactly the modes")
        scenarios.append(
            Scenario(
                id=str(data["id"]),
                title=str(data["title"]),
                category=data["category"],
                source=source,
                domain=str(data["domain"]),
                modes=modes,
                stimulus=str(data["stimulus"]),
                expected=expected,
                setup=tuple(data.get("setup") or ()),
                pass_line=str(data.get("pass_line") or ""),
                evidence=tuple(data.get("evidence") or ()),
                priority=str(data.get("priority", "MUST")),
            )
        )
    return scenarios


def _setup_packs(domain: Domain, setup: Sequence[Mapping[str, Any]]) -> tuple[Pack, ...]:
    packs: list[Pack] = [compile_pack(domain.day_one_text)]
    for i, step in enumerate(setup):
        if "autopilot_rule" in step:
            rule = step["autopilot_rule"]
            candidate = Candidate(str(rule["template"]), dict(rule["parameters"]))
            packs.append(compile_pack(build_pack(f"proof{i}", domain.agent, [candidate])))
        elif step.get("policy") != "day-one":
            raise ScenarioError(f"unknown setup step {step!r}")
    return tuple(packs)


async def run_scenario(
    scenario: Scenario,
    domains: Mapping[str, Domain],
    traces: Mapping[str, Mapping[str, Trace]],
    *,
    reader: Reader | None = None,
) -> ScenarioResult:
    start = time.perf_counter()
    domain = domains.get(scenario.domain)
    result = ScenarioResult(scenario.id, scenario.title, scenario.category, "fail")
    if domain is None:
        result.modes = {
            m: {"outcome": "skipped", "why": f"domain {scenario.domain!r} not loaded"}
            for m in scenario.modes
        }
        result.verdict = "partial"
        return result
    case: Case | None = next((c for c in cases_for(domain) if c.id == scenario.stimulus), None)
    if case is None:
        raise ScenarioError(f"{scenario.id}: unknown stimulus {scenario.stimulus!r}")
    bundle = PolicyBundle(_setup_packs(domain, scenario.setup))
    trace = traces.get(domain.name, {}).get(case.id)
    for mode in scenario.modes:
        want = scenario.expected[mode]
        allowed = want.get("outcome")
        allowed = [allowed] if isinstance(allowed, str) else list(allowed or [])
        if mode in ("baseline", "guard"):
            if trace is None:
                result.modes[mode] = {
                    "outcome": "skipped",
                    "why": "no recorded trace for the stimulus",
                }
                continue
            got = await replay(domain, case, trace, mode, lambda: bundle)  # type: ignore[arg-type]
            source = f"replay:{trace.source}"
        elif mode == "full":
            if reader is None:
                result.modes[mode] = {"outcome": "skipped", "why": "no reader model available"}
                continue
            got, _ = await run_live(
                domain, case, "full", Brains(_NoModel(), "none", reader), lambda: bundle
            )  # type: ignore[arg-type]
            source = "live reader"
            if got.outcome == "error":  # the reader could not run: not a pass, not a fail
                why = got.failures[0] if got.failures else "the reader failed"
                result.modes[mode] = {"outcome": "skipped", "why": why[:200]}
                continue
        else:
            result.modes[mode] = {"outcome": "skipped", "why": "the MCP gateway is not built"}
            continue
        rule_ok = "rule" not in want or (got.rule or "").endswith(str(want["rule"]))
        passed = got.outcome in allowed and rule_ok
        result.modes[mode] = {
            "outcome": got.outcome,
            "rule": got.rule,
            "expected": allowed,
            "expected_rule": want.get("rule"),
            "passed": passed,
            "source": source,
        }
    judged = [m for m in result.modes.values() if m["outcome"] != "skipped"]
    if judged and all(m["passed"] for m in judged):
        result.verdict = "pass" if len(judged) == len(result.modes) else "partial"
    result.seconds = time.perf_counter() - start
    return result


async def run_proof_suite(
    scenarios: Sequence[Scenario],
    domains: Mapping[str, Domain],
    traces: Mapping[str, Mapping[str, Trace]],
    *,
    reader: Reader | None = None,
) -> dict[str, Any]:
    results = [await run_scenario(s, domains, traces, reader=reader) for s in scenarios]
    return {
        "scenarios": [r.to_wire() for r in results],
        "passed": sum(r.verdict == "pass" for r in results),
        "partial": sum(r.verdict == "partial" for r in results),
        "failed": sum(r.verdict == "fail" for r in results),
        "total": len(results),
    }
