"""F22 Real-World Proof Suite: every shipped scenario loads, cites a real incident, and passes."""

from __future__ import annotations

from pathlib import Path

import pytest

from quarantix.arena.proof import ScenarioError, load_scenarios, run_proof_suite
from quarantix.arena.suite import load_traces
from quarantix.packs.model import Domain
from tests.packs._reader import HonestReader
from tests.packs.conftest import DOMAINS

ROOT = DOMAINS.parent
SCENARIOS = ROOT / "proof" / "scenarios"
INCIDENTS = ROOT / "docs" / "incidents.md"


def traces() -> dict:
    return {
        n: load_traces(ROOT / "redteam" / "traces" / f"{n}.json") for n in ("support", "devops")
    }


def test_scenarios_load_and_incident_replays_cite_incidents_md() -> None:
    scenarios = load_scenarios(SCENARIOS, INCIDENTS)
    assert {s.id for s in scenarios} >= {"RW-01", "RW-05", "RW-06", "RW-09"}
    for s in scenarios:
        if s.category == "incident_replay":
            assert f"## {s.source['incident']}." in INCIDENTS.read_text()


def test_an_uncited_incident_is_rejected(tmp_path: Path) -> None:
    text = (SCENARIOS / "rw-01-slack-phishing-link.yaml").read_text().replace("I-1", "I-99")
    (tmp_path / "x.yaml").write_text(text)
    with pytest.raises(ScenarioError, match=r"not in docs/incidents.md"):
        load_scenarios(tmp_path, INCIDENTS)


async def test_every_scenario_passes_with_a_reader(support: Domain, devops: Domain) -> None:
    report = await run_proof_suite(
        load_scenarios(SCENARIOS, INCIDENTS), {"support": support, "devops": devops}, traces(),
        reader=HonestReader(),
    )  # fmt: skip
    failing = [s for s in report["scenarios"] if s["verdict"] != "pass"]
    assert failing == [], failing
    rw05 = next(s for s in report["scenarios"] if s["scenario_id"] == "RW-05")
    assert rw05["modes"]["guard"]["outcome"] == "blocked"


async def test_without_a_reader_full_mode_is_skipped_never_passed(
    support: Domain, devops: Domain
) -> None:
    report = await run_proof_suite(
        load_scenarios(SCENARIOS, INCIDENTS), {"support": support, "devops": devops}, traces()
    )
    rw01 = next(s for s in report["scenarios"] if s["scenario_id"] == "RW-01")
    assert rw01["modes"]["full"]["outcome"] == "skipped" and rw01["verdict"] == "partial"
